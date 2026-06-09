import os
from pathlib import Path

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

    @property
    def db(self):
        if self._db is None:
            self._db = lancedb.connect(self.db_dir)
        return self._db

    def get_embedding_dimension(self) -> int:
        """Query Ollama to find the exact embedding dimension for the configured model."""
        try:
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": "hello"}
            resp = requests.post(url, json=payload, timeout=3.0)
            if resp.status_code == 200:
                emb = resp.json().get("embedding", [])
                if emb:
                    return len(emb)
        except Exception as e:
            print(f"Warning: Could not query Ollama to determine embedding size ({e}). Defaulting to 1024.")

        # Fallback dimensions depending on common models
        model = config.embedding_model.lower()
        if "nomic" in model:
            return 768
        elif "minilm" in model:
            return 384
        elif "gemma" in model:
            # embeddinggemma or similar
            return 1024
        return 1024

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
                pa.field("vector", pa.list_(pa.float32(), dim), nullable=False),
            ]
        )

    def _migrate_schema_if_needed(self, db_conn):
        print("MIGRATION: Evolving LanceDB schema to support nullable image_path and ocr_text...")
        try:
            tbl = db_conn.open_table(self.table_name)
            # 1. Load existing records via Arrow to avoid Pandas NaN float conversion issues
            pyarrow_table = tbl.to_arrow()
            records = pyarrow_table.to_pylist()

            # 2. Add 'ocr_text' column initialized to None for each record if not present
            for rec in records:
                if "ocr_text" not in rec:
                    rec["ocr_text"] = None

            # 3. Drop old table
            db_conn.drop_table(self.table_name)

            # 4. Recreate table with new schema
            dim = self.get_embedding_dimension()
            evolved_schema = self.get_schema(dim)
            new_tbl = db_conn.create_table(self.table_name, schema=evolved_schema)

            # 5. Load records back
            if records:
                new_tbl.add(records)
            self._table = new_tbl
            print("MIGRATION: Schema successfully migrated with all existing records preserved.")
        except Exception as e:
            print(f"Error during LanceDB schema migration: {e}")
            # Fallback to reopen the old table to avoid breaking startup
            self._table = db_conn.open_table(self.table_name)

    @property
    def table(self):
        if self._table is None:
            db_conn = self.db
            if self.table_name in db_conn.table_names():
                tbl = db_conn.open_table(self.table_name)
                schema = tbl.schema
                if "ocr_text" not in schema.names:
                    self._migrate_schema_if_needed(db_conn)
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
        return results[:limit]

    def get_all_records(self, limit: int = 500) -> list:
        """Fetch all records ordered by timestamp descending."""
        tbl = self.table
        # Retrieve all records (up to a large safety cap) to sort them globally, then slice to limit
        results = tbl.search().limit(100000).to_list()
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results[:limit]

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

    def nullify_expired_screenshot_path(self, record_id: str):
        """Set image_path = None for a specific record after purging its file."""
        try:
            self.table.update(where=f"id = '{record_id}'", values={"image_path": None})
            print(f"Set image_path = None for record {record_id}")
        except Exception as e:
            print(f"Error nullifying expired screenshot path for {record_id}: {e}")


db = VisionDB()
