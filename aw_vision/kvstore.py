"""Shared LanceDB key/value table plumbing for the config stores.

SettingsStore, PromptStore, MCPStore and SkillStore each hand-rolled the same
~40 lines of connection/table/upsert/delete code. This module is the single
composition building block replacing those copies. Field names are
configurable so the existing on-disk tables (``key``/``value`` and
``id``/``blob``) keep working without any data migration.
"""

from typing import Dict, List

from aw_vision.config import config


class LanceKVStore:
    """A tiny embedded string-key → string-value table with idempotent upserts."""

    def __init__(self, table_name: str, key_field: str = "key", value_field: str = "value"):
        self.table_name = table_name
        self.key_field = key_field
        self.value_field = value_field
        self._db_conn = None
        self._table = None

    @property
    def db_conn(self):
        if self._db_conn is None:
            import lancedb

            self._db_conn = lancedb.connect(config.db_dir)
        return self._db_conn

    @property
    def table(self):
        if self._table is None:
            conn = self.db_conn
            if self.table_name in conn.table_names():
                self._table = conn.open_table(self.table_name)
            else:
                import pyarrow as pa

                schema = pa.schema(
                    [
                        pa.field(self.key_field, pa.string(), nullable=False),
                        pa.field(self.value_field, pa.string(), nullable=False),
                    ]
                )
                self._table = conn.create_table(self.table_name, schema=schema)
        return self._table

    def rows(self, limit: int = 1000) -> List[Dict[str, str]]:
        """All rows as raw dicts; returns [] when the table is unreadable."""
        try:
            return self.table.search().limit(limit).to_list()
        except Exception as e:
            print(f"Warning: could not read LanceDB table '{self.table_name}': {e}")
            return []

    def items(self, limit: int = 1000) -> Dict[str, str]:
        """All rows as a {key: value} mapping."""
        out: Dict[str, str] = {}
        for r in self.rows(limit=limit):
            k = r.get(self.key_field)
            if k is not None:
                out[k] = r.get(self.value_field)
        return out

    def upsert(self, key: str, value: str):
        """Idempotently persist one row (delete-then-add, matching prior behavior)."""
        try:
            tbl = self.table
            try:
                tbl.delete(f"{self.key_field} = '{key}'")
            except Exception:
                pass
            tbl.add([{self.key_field: key, self.value_field: value}])
        except Exception as e:
            print(f"Error persisting '{key}' to LanceDB table '{self.table_name}': {e}")

    def delete(self, key: str):
        try:
            self.table.delete(f"{self.key_field} = '{key}'")
        except Exception as e:
            print(f"Error deleting '{key}' from LanceDB table '{self.table_name}': {e}")
