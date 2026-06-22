"""Background database-wide re-embedding migration and image-path resolution."""
import os
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa

from aw_vision.config import config


class ReembeddingMixin:
    def _resolve_record_image_paths(self, records: list) -> list:
        """Resolve on-disk processed image paths for a batch of records.

        Returns one entry per record: an absolute path string when the screenshot still exists,
        or None when it was never set or has been purged by the retention lifecycle.
        """
        processed_dir = config.screenshots_dir / "processed"
        paths = []
        for r in records:
            image_path_str = r.get("image_path")
            resolved = None
            if image_path_str:
                p = Path(image_path_str)
                if not p.is_absolute():
                    p = processed_dir / p.name
                if p.exists():
                    resolved = str(p)
            paths.append(resolved)
        return paths

    def trigger_batch_reembedding(self, force: bool = False):
        """Trigger an asynchronous, background, database-wide re-embedding migration."""
        import threading
        if self._reembedding_status["is_running"]:
            print("[Re-embedding] Migration is already running. Skipping trigger.")
            return

        t = threading.Thread(target=self._run_reembedding_migration, args=(force,), daemon=True)
        t.start()

    def _run_reembedding_migration(self, force: bool = False):
        import time
        from aw_vision.settings import settings_store
        from aw_vision.gemini import generate_gemini_batch_embeddings, is_internet_online
        from aw_vision.embedding import build_embedding_text, embedding_model_supports_image
        import requests

        provider = settings_store.get("provider")
        model = settings_store.get("gemini_embedding_model") if provider == "gemini" else settings_store.get("ollama_embedding_model")

        print(f"[Re-embedding] Starting database-wide re-embedding migration using {provider} - {model}...")

        # Only clear the error if it is NOT a Gemini migration fallback warning
        prev_error = self._reembedding_status.get("error")
        keep_error = False
        if prev_error and "Gemini Migration Error" in prev_error and provider != "gemini":
            keep_error = True

        self._reembedding_status.update({
            "is_running": True,
            "total_records": 0,
            "processed_records": 0,
            "error": prev_error if keep_error else None,
            "current_model": f"{provider}:{model}"
        })

        should_fallback_to_ollama = False
        fallback_friendly_error = None

        try:
            tbl = self.table
            records = tbl.search().limit(100000).to_list()
            total = len(records)
            self._reembedding_status["total_records"] = total

            if total == 0:
                print("[Re-embedding] No records found in database to re-embed.")
                self._reembedding_status["is_running"] = False
                return

            print(f"[Re-embedding] Found {total} records to re-embed.")

            batch_size = 100

            for i in range(0, total, batch_size):
                # Verify that the provider hasn't changed out from under us
                current_provider = settings_store.get("provider")
                current_model = settings_store.get("gemini_embedding_model") if current_provider == "gemini" else settings_store.get("ollama_embedding_model")
                if f"{current_provider}:{current_model}" != self._reembedding_status["current_model"]:
                    raise RuntimeError("Provider or model settings changed during migration. Aborting active migration.")

                batch_recs = records[i:i + batch_size]

                # Build right-sized embedding inputs consistent with live ingestion.
                texts = [build_embedding_text(r) for r in batch_recs]

                # Generate embeddings
                new_vectors = []
                if current_provider == "gemini":
                    if is_internet_online():
                        # Attach screenshots for multimodal-capable Gemini embedding models so the
                        # vector captures visual signal; text-only models skip the image payload.
                        img_paths = None
                        if embedding_model_supports_image(current_model):
                            img_paths = self._resolve_record_image_paths(batch_recs)
                        new_vectors = generate_gemini_batch_embeddings(texts, img_paths=img_paths)
                    else:
                        raise RuntimeError("Network offline during Gemini re-embedding migration.")
                else:
                    # Ollama batch embeddings
                    url = f"{config.ollama_host}/api/embeddings"
                    for text in texts:
                        try:
                            payload = {"model": current_model, "prompt": text, "keep_alive": 0}
                            resp = requests.post(url, json=payload, timeout=15.0)
                            if resp.status_code == 200:
                                new_vectors.append(resp.json().get("embedding", []))
                            else:
                                raise RuntimeError(f"Ollama embedding request failed: {resp.status_code}")
                        except Exception as e:
                            raise RuntimeError(f"Ollama embedding exception: {e}")

                if len(new_vectors) != len(batch_recs):
                    raise RuntimeError(f"Embedding generator returned {len(new_vectors)} vectors for {len(batch_recs)} records.")

                # Update records in LanceDB
                for rec, vec in zip(batch_recs, new_vectors):
                    tbl.update(where=f"id = '{rec['id']}'", values={"vector": vec})

                self._reembedding_status["processed_records"] += len(batch_recs)
                print(f"[Re-embedding] Progress: {self._reembedding_status['processed_records']}/{total}")
                time.sleep(0.5)

            print(f"[Re-embedding] Migration completed successfully. Processed {total} records.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            err_str = str(e)
            print(f"[Re-embedding] Error during re-embedding migration: {err_str}")

            is_gemini_terminal_error = False
            fallback_reason = ""

            if provider == "gemini":
                # Check for prepayment depletion or other quota limits
                if any(x in err_str.lower() for x in ["prepayment", "credit", "depleted", "resource_exhausted", "quota", "429"]):
                    is_gemini_terminal_error = True
                    fallback_reason = "Google Gemini API billing/quota exceeded (prepayment credits depleted)."
                elif any(x in err_str.lower() for x in ["api_key_invalid", "api key not valid", "invalid api key", "400", "401", "403"]):
                    is_gemini_terminal_error = True
                    fallback_reason = "Google Gemini API key authentication failed."
                elif any(x in err_str.lower() for x in ["returned 0 vectors", "returned empty", "empty embeddings", "mismatched", "0 vectors for", "empty list", "empty embedding values", "empty embeddings list"]):
                    is_gemini_terminal_error = True
                    fallback_reason = "Google Gemini API returned empty or mismatched vector responses."

            if is_gemini_terminal_error:
                fallback_friendly_error = (
                    f"Gemini Migration Error: {fallback_reason} "
                    "Automatically falling back to local Ollama embeddings to prevent ingestion lockup. "
                    "Please check your Google AI Studio project/billing at https://ai.studio/projects."
                )
                should_fallback_to_ollama = True
                print("[Re-embedding] Terminal Gemini API error encountered. Prepare fallback to Ollama.")
            else:
                self._reembedding_status["error"] = err_str
        finally:
            self._reembedding_status["is_running"] = False

        if should_fallback_to_ollama:
            self._reembedding_status["error"] = fallback_friendly_error
            try:
                print("[Re-embedding] Initiating fallback migration back to Ollama...")
                settings_store.set("provider", "ollama")
                settings_store.load_all()

                # Reset table reference so next access forces schema migration back to Ollama dimension
                self._table = None

                # Access table to trigger schema migration and start re-embedding
                _ = self.table
            except Exception as fallback_err:
                print(f"[Re-embedding] Error during automatic fallback to Ollama: {fallback_err}")
                self._reembedding_status["error"] = f"{fallback_friendly_error} (Ollama fallback failed: {fallback_err})"
