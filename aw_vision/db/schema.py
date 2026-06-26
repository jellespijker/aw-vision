"""LanceDB connection, vector-dimension probing, schema definition and migration."""
import os
import time
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa
import requests

from aw_vision.config import config


class SchemaMixin:
    @property
    def db(self):
        if self._db is None:
            self._db = lancedb.connect(self.db_dir)
        return self._db

    def get_embedding_dimension(self) -> int:
        """Return the active embedding vector dimension, memoized per provider/model.

        The Ollama probe (a live embed request that unloads the model) is expensive and was
        previously executed on every single embedding call, defeating model keep-alive. We now
        cache successful probes per (provider, model) so the cost is paid at most once.
        """
        from aw_vision.settings import settings_store
        provider = settings_store.get("provider")
        if provider == "gemini":
            # gemini-embeddings-002 has 3072 dimensions, as approved by the user.
            return 3072

        # Else, Ollama provider
        model = settings_store.get("ollama_embedding_model") or config.embedding_model
        cache_key = f"ollama:{model}"
        if cache_key in self._dim_cache:
            return self._dim_cache[cache_key]

        try:
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": model, "prompt": "hello", "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                emb = resp.json().get("embedding", [])
                if emb:
                    self._dim_cache[cache_key] = len(emb)
                    return len(emb)
        except Exception as e:
            print(f"Warning: Could not query Ollama to determine embedding size ({e}). Defaulting to 768.")

        # Fallback dimensions depending on common models. Not cached so a real probe can succeed
        # once Ollama becomes reachable (avoids sticking a wrong default while the model warms up).
        ml = model.lower()
        if "nomic" in ml:
            return 768
        elif "minilm" in ml:
            return 384
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
