import os
from pathlib import Path
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

    @property
    def db(self):
        if self._db is None:
            self._db = lancedb.connect(self.db_dir)
        return self._db

    def get_embedding_dimension(self) -> int:
        """Query Ollama to find the exact embedding dimension for the configured model."""
        try:
            url = f"{config.ollama_host}/api/embeddings"
            payload = {"model": config.embedding_model, "prompt": "hello", "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                emb = resp.json().get("embedding", [])
                if emb:
                    return len(emb)
        except Exception as e:
            print(f"Warning: Could not query Ollama to determine embedding size ({e}). Defaulting to 768.")

        # Fallback dimensions depending on common models
        model = config.embedding_model.lower()
        if "nomic" in model:
            return 768
        elif "minilm" in model:
            return 384
        elif "gemma" in model:
            # embeddinggemma is 768
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
                pa.field("vector", pa.list_(pa.float32(), dim), nullable=False),
            ]
        )

    def _migrate_schema_if_needed(self, db_conn, active_dim: Optional[int] = None):
        print("MIGRATION: Evolving LanceDB schema and updating record layouts...")
        try:
            tbl = db_conn.open_table(self.table_name)
            # 1. Load existing records via Arrow to avoid Pandas NaN float conversion issues
            pyarrow_table = tbl.to_arrow()
            records = pyarrow_table.to_pylist()

            # Determine target dimension
            dim = active_dim if active_dim is not None else self.get_embedding_dimension()

            # 2. Update 'ocr_text', 'human_labeled', 'unique_things', and vector dimension for each record if needed
            for rec in records:
                if "ocr_text" not in rec:
                    rec["ocr_text"] = None
                if "human_labeled" not in rec:
                    rec["human_labeled"] = False
                if "unique_things" not in rec:
                    rec["unique_things"] = None

                # Check and normalize vector dimension
                vec = rec.get("vector")
                if vec is not None:
                    if len(vec) < dim:
                        rec["vector"] = vec + [0.0] * (dim - len(vec))
                    elif len(vec) > dim:
                        rec["vector"] = vec[:dim]

            # 3. Drop old table
            db_conn.drop_table(self.table_name)

            # 4. Recreate table with new schema
            evolved_schema = self.get_schema(dim)
            new_tbl = db_conn.create_table(self.table_name, schema=evolved_schema)

            # 5. Load records back
            if records:
                new_tbl.add(records)
            self._table = new_tbl
            print(f"MIGRATION: Schema successfully migrated to vector size {dim} with {len(records)} existing records preserved.")
        except Exception as e:
            import traceback
            traceback.print_exc()
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

                # Get dimensions
                try:
                    table_dim = schema.field("vector").type.list_size
                except Exception:
                    table_dim = 768

                active_dim = self.get_embedding_dimension()

                if (
                    "ocr_text" not in schema.names
                    or "human_labeled" not in schema.names
                    or "unique_things" not in schema.names
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


db = VisionDB()
