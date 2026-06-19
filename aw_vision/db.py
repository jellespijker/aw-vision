import os
from pathlib import Path
import time
from typing import Optional

import lancedb
import pyarrow as pa
import requests

from aw_vision.config import config


class VisionDB:
    def __init__(self):
        self.db_dir = config.db_dir
        self._db = None
        self._table = None
        self.table_name = "screenshots"
        self.projects_table_name = "projects"
        self._projects_table = None
        self._reembedding_status = {
            "is_running": False,
            "total_records": 0,
            "processed_records": 0,
            "error": None,
            "current_model": ""
        }

    @property
    def db(self):
        if self._db is None:
            self._db = lancedb.connect(self.db_dir)
        return self._db

    def get_embedding_dimension(self) -> int:
        """Query Ollama or return Gemini dimension based on configured settings."""
        from aw_vision.settings import settings_store
        provider = settings_store.get("provider")
        if provider == "gemini":
            # gemini-embeddings-002 has 3072 dimensions, as approved by the user.
            return 3072

        # Else, Ollama provider
        try:
            url = f"{config.ollama_host}/api/embeddings"
            model = settings_store.get("ollama_embedding_model") or config.embedding_model
            payload = {"model": model, "prompt": "hello", "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                emb = resp.json().get("embedding", [])
                if emb:
                    return len(emb)
        except Exception as e:
            print(f"Warning: Could not query Ollama to determine embedding size ({e}). Defaulting to 768.")

        # Fallback dimensions depending on common models
        model = (settings_store.get("ollama_embedding_model") or config.embedding_model).lower()
        if "nomic" in model:
            return 768
        elif "minilm" in model:
            return 384
        elif "gemma" in model:
            return 768
        return 768

    def get_schema(self, dim: int) -> pa.Schema:
        """Create PyArrow schema with the dynamic vector dimension."""
        return pa.schema(
            [
                pa.field("id", pa.string(), nullable=False),
                pa.field("timestamp", pa.float64(), nullable=False),
                pa.field("image_path", pa.string(), nullable=True),
                pa.field("window_title", pa.string(), nullable=True),
                pa.field("app_name", pa.string(), nullable=True),
                pa.field("is_afk", pa.bool_(), nullable=True),
                pa.field("description", pa.string(), nullable=True),
                pa.field("ocr_text", pa.string(), nullable=True),
                pa.field("tags", pa.list_(pa.string()), nullable=True),
                pa.field("project_number", pa.string(), nullable=True),
                pa.field("human_labeled", pa.bool_(), nullable=True),
                pa.field("unique_things", pa.string(), nullable=True),
                pa.field("duration_ocr", pa.float64(), nullable=True),
                pa.field("duration_vision", pa.float64(), nullable=True),
                pa.field("duration_embedding", pa.float64(), nullable=True),
                pa.field("duration_total", pa.float64(), nullable=True),
                pa.field("vector", pa.list_(pa.float32(), dim), nullable=False),
            ]
        )

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

                # Build texts and matching physical image paths
                texts = []
                img_paths = []
                processed_dir = config.screenshots_dir / "processed"
                for r in batch_recs:
                    desc = r.get("description") or ""
                    ocr = r.get("ocr_text") or ""
                    joint_text = f"Description: {desc}\n\nExtracted Screen Text: {ocr}"
                    texts.append(joint_text)

                    image_path_str = r.get("image_path")
                    if image_path_str:
                        p = Path(image_path_str)
                        if not p.is_absolute():
                            p = processed_dir / p.name
                        if p.exists():
                            img_paths.append(str(p))
                        else:
                            img_paths.append(None)
                    else:
                        img_paths.append(None)

                # Generate embeddings
                new_vectors = []
                if current_provider == "gemini":
                    if is_internet_online():
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

    def _migrate_schema_if_needed(self, db_conn, active_dim: Optional[int] = None):
        print("MIGRATION: Evolving LanceDB schema and updating record layouts...")
        try:
            tbl = db_conn.open_table(self.table_name)
            pyarrow_table = tbl.to_arrow()
            records = pyarrow_table.to_pylist()

            dim = active_dim if active_dim is not None else self.get_embedding_dimension()

            for rec in records:
                if "ocr_text" not in rec:
                    rec["ocr_text"] = None
                if "human_labeled" not in rec:
                    rec["human_labeled"] = False
                if "unique_things" not in rec:
                    rec["unique_things"] = None
                if "duration_ocr" not in rec:
                    rec["duration_ocr"] = None
                if "duration_vision" not in rec:
                    rec["duration_vision"] = None
                if "duration_embedding" not in rec:
                    rec["duration_embedding"] = None
                if "duration_total" not in rec:
                    rec["duration_total"] = None

                vec = rec.get("vector")
                if vec is not None:
                    if len(vec) < dim:
                        rec["vector"] = vec + [0.0] * (dim - len(vec))
                    elif len(vec) > dim:
                        rec["vector"] = vec[:dim]

            db_conn.drop_table(self.table_name)

            evolved_schema = self.get_schema(dim)
            new_tbl = db_conn.create_table(self.table_name, schema=evolved_schema)

            if records:
                new_tbl.add(records)
            self._table = new_tbl
            print(f"MIGRATION: Schema successfully migrated to vector size {dim} with {len(records)} existing records preserved.")

            self.trigger_batch_reembedding()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error during LanceDB schema migration: {e}")
            self._table = db_conn.open_table(self.table_name)

    @property
    def table(self):
        if self._table is None:
            db_conn = self.db
            if self.table_name in db_conn.table_names():
                tbl = db_conn.open_table(self.table_name)
                schema = tbl.schema

                try:
                    table_dim = schema.field("vector").type.list_size
                except Exception:
                    table_dim = 768

                active_dim = self.get_embedding_dimension()

                if (
                    "ocr_text" not in schema.names
                    or "human_labeled" not in schema.names
                    or "unique_things" not in schema.names
                    or "duration_ocr" not in schema.names
                    or "duration_vision" not in schema.names
                    or "duration_embedding" not in schema.names
                    or "duration_total" not in schema.names
                    or table_dim != active_dim
                ):
                    self._migrate_schema_if_needed(db_conn, active_dim=active_dim)
                else:
                    self._table = tbl
            else:
                dim = self.get_embedding_dimension()
                schema = self.get_schema(dim)
                self._table = db_conn.create_table(self.table_name, schema=schema)
        return self._table

    def insert_screenshot(self, record: dict):
        """Insert a processed screenshot record into LanceDB.

        record should contain:
        - id: str
        - timestamp: float
        - image_path: str
        - window_title: str
        - app_name: str
        - is_afk: bool
        - description: str
        - tags: list[str]
        - project_number: str
        - vector: list[float]
        """
        # Ensure tags are a list of strings
        if "tags" in record and isinstance(record["tags"], str):
            record["tags"] = [tag.strip() for item in record["tags"].split(",") for tag in [item.strip()] if tag]

        # Ensure idempotency by deleting any existing record with the same ID first
        try:
            self.table.delete(f"id = '{record['id']}'")
        except Exception as e:
            print(f"Warning: Could not delete existing record '{record['id']}' before insert: {e}")

        self.table.add([record])

    def search_semantic(self, query_vector: list, limit: int = 5, where: str = None) -> list:
        """Perform a semantic vector similarity search on LanceDB, optionally with SQL filtering."""
        tbl = self.table
        query = tbl.search(query_vector).metric("cosine")
        if where:
            query = query.where(where)
        results = query.limit(limit).to_list()
        return results

    def query_metadata(self, where: str, limit: int = 100) -> list:
        """Filter records by metadata using SQL-like queries."""
        tbl = self.table
        # LanceDB tables can be searched/filtered using SQL where clauses
        results = tbl.search().where(where).limit(100000).to_list()
        # Sort by timestamp descending
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # Deduplicate by id (first seen is newest)
        deduped = []
        seen = set()
        for r in results:
            rid = r.get("id")
            if rid not in seen:
                seen.add(rid)
                deduped.append(r)
        return deduped[:limit]

    def get_all_records(self, limit: int = 500) -> list:
        """Fetch all records ordered by timestamp descending."""
        tbl = self.table
        # Retrieve all records (up to a large safety cap) to sort them globally, then slice to limit
        results = tbl.search().limit(100000).to_list()
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # Deduplicate by id (first seen is newest)
        deduped = []
        seen = set()
        for r in results:
            rid = r.get("id")
            if rid not in seen:
                seen.add(rid)
                deduped.append(r)
        return deduped[:limit]

    def get_processing_stats(self) -> dict:
        """Query all records and calculate mean, min, and max processing times for each phase."""
        try:
            tbl = self.table
            # Select only the duration fields to maximize query execution performance
            records = tbl.search().select(["duration_ocr", "duration_vision", "duration_embedding", "duration_total"]).limit(100000).to_list()
        except Exception as e:
            print(f"Error loading records for processing stats: {e}")
            return {}

        ocr_times = []
        vision_times = []
        emb_times = []
        total_times = []

        for r in records:
            ocr_val = r.get("duration_ocr")
            # Only count active model executions (greater than 0.0s) to keep stats mathematically accurate
            if ocr_val is not None and ocr_val > 0.0:
                ocr_times.append(ocr_val)

            vis_val = r.get("duration_vision")
            if vis_val is not None and vis_val > 0.0:
                vision_times.append(vis_val)

            emb_val = r.get("duration_embedding")
            if emb_val is not None and emb_val > 0.0:
                emb_times.append(emb_val)

            tot_val = r.get("duration_total")
            if tot_val is not None and tot_val > 0.0:
                total_times.append(tot_val)

        def calc_stats(times):
            if not times:
                return {"mean": 0.0, "min": 0.0, "max": 0.0, "count": 0}
            return {
                "mean": round(sum(times) / len(times), 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2),
                "count": len(times)
            }

        return {
            "ocr": calc_stats(ocr_times),
            "vision": calc_stats(vision_times),
            "embedding": calc_stats(emb_times),
            "total": calc_stats(total_times),
        }

    def get_project_statistics(self) -> dict:
        """Aggregate total counted hours per project.

        Assumes each screenshot represents config.screenshot_interval seconds of active work.
        """
        try:
            records = self.get_all_records(limit=10000)
        except Exception:
            return {}

        stats = {}
        interval_hours = config.screenshot_interval / 3600.0

        for r in records:
            p_num = r.get("project_number")
            if not p_num:
                p_num = "None"

            # Count only if user wasn't AFK
            if r.get("is_afk"):
                continue

            stats[p_num] = stats.get(p_num, 0.0) + interval_hours

        return stats

    def get_binned_timeline(self, start_time: float, end_time: float, resolution_seconds: float) -> dict:
        """Query and aggregate active screenshot durations binned by resolution_seconds.

        Returns:
            dict mapping project_number to a list of dicts containing binned times.
        """
        try:
            where_clause = f"timestamp >= {start_time} AND timestamp <= {end_time}"
            records = self.query_metadata(where_clause, limit=100000)
        except Exception as e:
            print(f"Error querying binned timeline metadata: {e}")
            records = []

        # Align bins to multiples of resolution_seconds
        aligned_start = (start_time // resolution_seconds) * resolution_seconds

        # Determine number of bins, cap at 5000 for safety
        if resolution_seconds <= 0:
            resolution_seconds = 3600.0

        num_bins = int((end_time - aligned_start) // resolution_seconds) + 1
        if num_bins > 5000:
            num_bins = 5000

        # Get configured project numbers and Unclassified
        try:
            projects_list = config.load_projects()
            project_numbers = [p["project_number"] for p in projects_list] + ["Unclassified"]
        except Exception:
            project_numbers = ["Unclassified"]

        bins_by_project = {p_num: [0.0] * num_bins for p_num in project_numbers}
        interval_seconds = config.screenshot_interval

        for r in records:
            # Skip if user was AFK
            if r.get("is_afk"):
                continue

            p_num = r.get("project_number")
            if not p_num or p_num.strip() == "" or p_num.lower() == "none":
                p_num = "Unclassified"

            ts = r.get("timestamp")
            if ts < aligned_start:
                continue

            bin_idx = int((ts - aligned_start) // resolution_seconds)
            if 0 <= bin_idx < num_bins:
                if p_num not in bins_by_project:
                    bins_by_project[p_num] = [0.0] * num_bins
                bins_by_project[p_num][bin_idx] += interval_seconds

        # Format results for the frontend
        result = {}
        for p_num, durations in bins_by_project.items():
            project_bins = []
            for idx, dur in enumerate(durations):
                b_start = aligned_start + idx * resolution_seconds
                b_end = b_start + resolution_seconds
                dur_capped = min(dur, resolution_seconds)
                project_bins.append({
                    "start_time": b_start,
                    "end_time": b_end,
                    "duration_seconds": round(dur_capped, 1)
                })
            result[p_num] = project_bins

        return {
            "aligned_start": aligned_start,
            "resolution_seconds": resolution_seconds,
            "num_bins": num_bins,
            "projects": result
        }

    def get_all_unique_tags(self) -> list[str]:
        """Get all unique tags present in the database."""
        try:
            records = self.get_all_records(limit=10000)
        except Exception as e:
            print(f"Error querying unique tags: {e}")
            return []

        unique_tags = set()
        for r in records:
            tags = r.get("tags")
            if tags:
                for t in tags:
                    if t:
                        unique_tags.add(t.strip())
        return sorted(list(unique_tags))

    def get_record_by_id(self, record_id: str) -> dict | None:
        """Fetch a specific record by its ID."""
        try:
            results = self.table.search().where(f"id = '{record_id}'").limit(1).to_list()
            return results[0] if results else None
        except Exception as e:
            print(f"Error fetching record {record_id} by ID: {e}")
            return None

    def nullify_expired_screenshot_path(self, record_id: str):
        """Set image_path = None for a specific record after purging its file."""
        try:
            self.table.update(where=f"id = '{record_id}'", values={"image_path": None})
            print(f"Set image_path = None for record {record_id}")
        except Exception as e:
            print(f"Error nullifying expired screenshot path for {record_id}: {e}")

    def update_project_label(self, record_id: str, project_number: Optional[str], human_labeled: bool = True):
        """Update the project number and human_labeled flag for a specific record."""
        try:
            self.table.update(
                where=f"id = '{record_id}'",
                values={"project_number": project_number, "human_labeled": human_labeled}
            )
            print(f"Updated project_number to '{project_number}' and human_labeled to {human_labeled} for record {record_id}")
        except Exception as e:
            print(f"Error updating project label for record {record_id}: {e}")
            raise e

    def get_past_neighbor(self, timestamp: float) -> dict | None:
        """Get the closest snapshot record immediately preceding the given timestamp."""
        try:
            results = self.query_metadata(f"timestamp < {timestamp}", limit=1)
            return results[0] if results else None
        except Exception as e:
            print(f"Error fetching past neighbor for {timestamp}: {e}")
            return None

    def get_future_neighbor(self, timestamp: float) -> dict | None:
        """Get the closest snapshot record immediately succeeding the given timestamp."""
        try:
            tbl = self.table
            results = tbl.search().where(f"timestamp > {timestamp}").limit(100000).to_list()
            results.sort(key=lambda x: x.get("timestamp", 0.0), reverse=False)
            return results[0] if results else None
        except Exception as e:
            print(f"Error fetching future neighbor for {timestamp}: {e}")
            return None

    def get_app_project_frequencies(self, app_name: str) -> dict[str, float]:
        """Get project numbers associated with an app_name, with weights (human_labeled = 5.0, auto = 1.0)."""
        if not app_name:
            return {}
        try:
            escaped_app = app_name.replace("'", "''")
            records = self.query_metadata(f"app_name = '{escaped_app}'", limit=100)

            freqs = {}
            for r in records:
                proj = r.get("project_number")
                if not proj:
                    continue
                weight = 5.0 if r.get("human_labeled") else 1.0
                freqs[proj] = freqs.get(proj, 0.0) + weight
            return freqs
        except Exception as e:
            print(f"Error querying app project frequencies for '{app_name}': {e}")
            return {}

    def get_similar_labeled_snapshots(self, vector: list[float], tags: list[str] = None, app_name: str = None, limit: int = 10) -> list[dict]:
        """Perform a semantic vector similarity search and filter/boost based on human_labeled status and tags."""
        try:
            # Step 1: Run semantic search in LanceDB
            raw_results = self.search_semantic(vector, limit=20)

            processed_results = []
            for r in raw_results:
                proj = r.get("project_number")
                if not proj:
                    continue

                # Base similarity calculation from distance
                dist = r.get("_distance", 1.0)
                sim = 1.0 / (1.0 + dist)

                score = sim
                # Human labeled boost (5x multiplier)
                is_human = bool(r.get("human_labeled", False))
                if is_human:
                    score *= 5.0

                # Common tags bonus
                r_tags = r.get("tags") or []
                if tags and r_tags:
                    common = set(tags).intersection(set(r_tags))
                    score += 0.2 * len(common)

                # Same app bonus
                if app_name and r.get("app_name") == app_name:
                    score += 0.3

                processed_results.append({
                    "id": r.get("id"),
                    "project_number": proj,
                    "score": score,
                    "human_labeled": is_human,
                    "description": r.get("description"),
                    "window_title": r.get("window_title"),
                    "app_name": r.get("app_name"),
                    "tags": r_tags,
                })

            # Sort by total calculated score descending
            processed_results.sort(key=lambda x: x["score"], reverse=True)
            return processed_results[:limit]
        except Exception as e:
            print(f"Error scoring similar labeled snapshots: {e}")
            return []

    def get_similar_labeled_snapshots_by_metadata(self, app_name: str, window_title: str, limit: int = 5) -> list[dict]:
        """Perform a fast metadata SQL-like query and keyword match to find similar labeled snapshots without loading any ML embedding models."""
        import re
        try:
            if not app_name or app_name == "Unknown":
                return []

            # Escape single quotes for SQL-like query safety
            safe_app = app_name.replace("'", "''")

            # Retrieve snapshots for the same app that have an assigned project number
            where_clause = f"app_name = '{safe_app}' AND project_number IS NOT NULL AND project_number != 'None'"
            results = self.query_metadata(where_clause, limit=100)
            if not results:
                return []

            # Extract lowercase alphanumeric keywords from the current window_title
            keywords = [w.lower() for w in re.split(r"\W+", window_title or "") if len(w) >= 3]

            processed_results = []
            for r in results:
                proj = r.get("project_number")
                if not proj:
                    continue

                score = 1.0
                # Human labeled boost
                is_human = bool(r.get("human_labeled", False))
                if is_human:
                    score += 5.0

                # Keyword title overlap boost
                r_title = r.get("window_title", "").lower()
                matches = 0
                for kw in keywords:
                    if kw in r_title:
                        matches += 1
                if keywords:
                    score += (matches / len(keywords)) * 2.0

                processed_results.append({
                    "id": r.get("id"),
                    "project_number": proj,
                    "score": score,
                    "human_labeled": is_human,
                    "description": r.get("description"),
                    "window_title": r.get("window_title"),
                    "app_name": r.get("app_name"),
                    "tags": r.get("tags") or [],
                })

            # Sort by total calculated score descending
            processed_results.sort(key=lambda x: x["score"], reverse=True)
            return processed_results[:limit]
        except Exception as e:
            print(f"Error scoring metadata-similar snapshots: {e}")
            return []

    @property
    def projects_table(self):
        if self._projects_table is None:
            db_conn = self.db
            if self.projects_table_name in db_conn.table_names():
                self._projects_table = db_conn.open_table(self.projects_table_name)
                # Ensure we run migration check if empty
                try:
                    count = len(self._projects_table.search().limit(1).to_list())
                    if count == 0:
                        self.migrate_legacy_projects_if_needed()
                except Exception:
                    pass
            else:
                schema = pa.schema([
                    pa.field("project_number", pa.string(), nullable=False),
                    pa.field("description", pa.string(), nullable=True),
                    pa.field("work_entailment", pa.string(), nullable=True),
                    pa.field("is_active", pa.bool_(), nullable=False),
                    pa.field("created_at", pa.float64(), nullable=False),
                ])
                self._projects_table = db_conn.create_table(self.projects_table_name, schema=schema)
                self.migrate_legacy_projects_if_needed()
        return self._projects_table

    def migrate_legacy_projects_if_needed(self):
        """If projects table is empty and legacy projects.json exists, migrate it."""
        try:
            tbl = self.projects_table
            count = len(tbl.search().limit(1).to_list())

            p_file = config.projects_file
            if count == 0 and p_file.exists():
                print(f"[Migration] Legacy {p_file} found and projects table is empty. Starting migration...")
                import json
                with open(p_file, "r", encoding="utf-8") as f:
                    legacy_projects = json.load(f)

                records = []
                for idx, p in enumerate(legacy_projects):
                    records.append({
                        "project_number": p["project_number"],
                        "description": p.get("description", ""),
                        "work_entailment": p.get("work_entailment", ""),
                        "is_active": p.get("is_active", True),
                        "created_at": float(time.time() - (len(legacy_projects) - idx)),  # preserve order loosely
                    })

                if records:
                    tbl.add(records)
                    print(f"[Migration] Successfully migrated {len(records)} projects from legacy JSON.")

                # Rename projects.json to projects.json.bak
                bak_file = p_file.with_suffix(".json.bak")
                p_file.rename(bak_file)
                print(f"[Migration] Renamed {p_file} to {bak_file}")
        except Exception as e:
            print(f"[Migration] Error during legacy projects migration: {e}")

    def load_projects(self, include_inactive: bool = False) -> list[dict]:
        """Load projects from LanceDB.

        If include_inactive is False, only return active ones.
        """
        try:
            tbl = self.projects_table
            results = tbl.search().limit(1000).to_list()
            # Sort by created_at ascending so older projects appear first
            results.sort(key=lambda x: x.get("created_at", 0.0))
            if not include_inactive:
                results = [r for r in results if r.get("is_active", True)]
            return results
        except Exception as e:
            print(f"Error loading projects from LanceDB: {e}")
            return []

    def save_project(self, project: dict):
        """Upsert a project in LanceDB."""
        try:
            tbl = self.projects_table
            p_num = project["project_number"]
            escaped_num = p_num.replace("'", "''")
            # Delete existing with same project_number
            try:
                tbl.delete(f"project_number = '{escaped_num}'")
            except Exception as e:
                print(f"Warning: Could not delete project '{p_num}' before save: {e}")

            # Ensure default values
            record = {
                "project_number": p_num,
                "description": project.get("description") or "",
                "work_entailment": project.get("work_entailment") or "",
                "is_active": bool(project.get("is_active", True)),
                "created_at": float(project.get("created_at") or time.time()),
            }
            tbl.add([record])
            print(f"Saved project {p_num} to LanceDB.")
        except Exception as e:
            print(f"Error saving project {project.get('project_number')} to LanceDB: {e}")
            raise e

    def delete_project(self, project_number: str):
        """Delete a project from LanceDB."""
        try:
            tbl = self.projects_table
            escaped_num = project_number.replace("'", "''")
            tbl.delete(f"project_number = '{escaped_num}'")
            print(f"Deleted project {project_number} from LanceDB.")
        except Exception as e:
            print(f"Error deleting project {project_number} from LanceDB: {e}")
            raise e

    def toggle_project_active(self, project_number: str) -> bool:
        """Toggle the active status of a project in LanceDB."""
        try:
            tbl = self.projects_table
            escaped_num = project_number.replace("'", "''")
            results = tbl.search().where(f"project_number = '{escaped_num}'").limit(1).to_list()
            if not results:
                raise ValueError(f"Project '{project_number}' not found.")

            proj = results[0]
            new_active = not proj.get("is_active", True)
            tbl.update(where=f"project_number = '{escaped_num}'", values={"is_active": new_active})
            print(f"Toggled project {project_number} active status to {new_active}.")
            return new_active
        except Exception as e:
            print(f"Error toggling project {project_number} active status: {e}")
            raise e


db = VisionDB()
