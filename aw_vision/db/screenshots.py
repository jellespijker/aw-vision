"""Screenshot record CRUD, semantic/metadata queries, neighbors and tag lookup."""
import os
import time
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa
import requests

from aw_vision.config import config


class ScreenshotsMixin:
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

    def get_all_unique_tags(self) -> list[str]:
        """Get all unique tags present in the database.

        Projects only the ``tags`` column (avoiding loading descriptions, OCR and heavy vectors)
        and memoizes the result with a short TTL, so repeated calls during a processing batch do
        not trigger a full-table scan per screenshot.
        """
        now = time.time()
        if self._tags_cache is not None and (now - self._tags_cache_time) < self._tags_cache_ttl:
            return self._tags_cache

        try:
            tbl = self.table
            records = tbl.search().select(["tags"]).limit(100000).to_list()
        except Exception as e:
            print(f"Error querying unique tags: {e}")
            return self._tags_cache if self._tags_cache is not None else []

        unique_tags = set()
        for r in records:
            tags = r.get("tags")
            if tags:
                for t in tags:
                    if t:
                        unique_tags.add(t.strip())

        self._tags_cache = sorted(unique_tags)
        self._tags_cache_time = now
        return self._tags_cache

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

    def update_user_context(self, record_id: str, user_context: Optional[str]):
        """Update the free-text user-provided context note for a specific record."""
        try:
            self.table.update(where=f"id = '{record_id}'", values={"user_context": user_context})
            print(f"Updated user_context for record {record_id} ({len(user_context or '')} chars)")
        except Exception as e:
            print(f"Error updating user context for record {record_id}: {e}")
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
