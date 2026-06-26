"""Projects table: schema bootstrap, legacy JSON migration and project CRUD."""
import os
import time
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa
import requests

from aw_vision.config import config


class ProjectsMixin:
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
