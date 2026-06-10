import base64
import hashlib
import os
import socket
import uuid
from pathlib import Path
from typing import Any, Dict

from cryptography.fernet import Fernet

from aw_vision.config import config


def get_encryption_key() -> bytes:
    """Combine system-unique attributes to derive a consistent, 32-byte key for Fernet."""
    try:
        hostname = socket.gethostname()
        user_home = os.path.expanduser("~")

        # Cross-platform secure hardware identifier
        mac = str(uuid.getnode())

        # Combine unique traits into key material
        key_material = f"aw-vision-secure-{hostname}-{user_home}-{mac}"
        hashed = hashlib.sha256(key_material.encode("utf-8")).digest()

        return base64.urlsafe_b64encode(hashed)
    except Exception as e:
        # Fallback to local hardcoded salt hash (extremely unlikely to fail)
        print(f"Error deriving system encryption key, using fallback: {e}")
        fallback = hashlib.sha256(b"aw-vision-system-fallback-salt-key-derivation").digest()
        return base64.urlsafe_b64encode(fallback)


def encrypt_value(value: str) -> str:
    """Encrypt a string value using AES-256-CBC via Fernet."""
    if not value:
        return ""
    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.encrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Encryption error: {e}")
        return ""


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a string value using AES-256-CBC via Fernet."""
    if not encrypted_value:
        return ""
    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""


class SettingsStore:
    def __init__(self):
        self._db_conn = None
        self._table = None
        self.table_name = "settings"
        self._cache: Dict[str, str] = {}
        self._defaults = {
            "provider": "ollama",
            "gemini_api_key": "",
            "gemini_llm_model": "gemini-2.0-flash",
            "gemini_embedding_model": "gemini-embeddings-002",
            "gemini_context_size": "1048576",
            "gemini_rate_limit_delay": "4.0",
            "ollama_vision_model": "gemma4:e2b-it-qat",
            "ollama_ocr_model": "glm-ocr:q8_0",
            "ollama_embedding_model": "embeddinggemma",
            "ollama_context_size": "8192",
            "agent_provider": "ollama",
            "agent_model": "gemma4:e2b-it-qat",
            "agent_context_size": "8192",
            "max_ocr_chars": "1200",
            "max_tool_result_chars": "3000",
        }
        self.load_all()

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
                    [pa.field("key", pa.string(), nullable=False), pa.field("value", pa.string(), nullable=False)]
                )
                self._table = conn.create_table(self.table_name, schema=schema)
        return self._table

    def load_all(self):
        """Pre-populate with defaults and load all saved entries from the settings table."""
        self._cache = self._defaults.copy()
        try:
            tbl = self.table
            records = tbl.search().limit(100).to_list()
            for r in records:
                k = r.get("key")
                v = r.get("value")
                if k in self._cache:
                    if k == "gemini_api_key" and v:
                        self._cache[k] = decrypt_value(v)
                    else:
                        self._cache[k] = v
        except Exception as e:
            print(f"Warning: Could not load settings from LanceDB, using defaults. Error: {e}")

    def get(self, key: str) -> str:
        """Retrieve a setting string value, returning default if not configured."""
        return self._cache.get(key, self._defaults.get(key, ""))

    def get_int(self, key: str) -> int:
        """Retrieve a setting converted to integer."""
        val = self.get(key)
        try:
            return int(val)
        except (ValueError, TypeError):
            return int(self._defaults.get(key, "0"))

    def get_float(self, key: str) -> float:
        """Retrieve a setting converted to float."""
        val = self.get(key)
        try:
            return float(val)
        except (ValueError, TypeError):
            return float(self._defaults.get(key, "0.0"))

    def set(self, key: str, value: Any):
        """Save a single setting in LanceDB and update memory cache."""
        val_str = str(value)
        self._cache[key] = val_str

        # Encrypt the Gemini API key before storing in the database file
        db_val = val_str
        if key == "gemini_api_key":
            db_val = encrypt_value(val_str)

        try:
            tbl = self.table
            # Ensure idempotency by deleting the existing key first
            try:
                tbl.delete(f"key = '{key}'")
            except Exception:
                pass
            tbl.add([{"key": key, "value": db_val}])
        except Exception as e:
            print(f"Error persisting setting '{key}' to database: {e}")

    def get_all_masked(self) -> Dict[str, Any]:
        """Get all settings with sensitive API keys masked for safe frontend rendering."""
        res = {}
        for k, v in self._cache.items():
            if k == "gemini_api_key":
                res[k] = "••••••••" if v else ""
            elif k in (
                "gemini_context_size",
                "ollama_context_size",
                "agent_context_size",
                "max_ocr_chars",
                "max_tool_result_chars",
            ):
                try:
                    res[k] = int(v)
                except Exception:
                    res[k] = v
            elif k == "gemini_rate_limit_delay":
                try:
                    res[k] = float(v)
                except Exception:
                    res[k] = v
            else:
                res[k] = v
        return res


settings_store = SettingsStore()
