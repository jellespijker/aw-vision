"""Claude Skills integration.

Users can upload Claude Skills (a ``SKILL.md`` markdown file with YAML
frontmatter, or a ``.zip`` bundle containing one) and assign each skill to the
same pipeline/agent slots used for MCP servers. Assigned skills have their
instructions injected into the corresponding prompt as expert guidance, steering
context extraction and project classification.
"""

import base64
import io
import json
import os
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

from aw_vision.config import config
from aw_vision.mcp_manager import VALID_SLOT_IDS

# Injected skill instructions are capped per skill so a large skill cannot blow
# past the (often small, local) model context window.
MAX_SKILL_CHARS = 6000


def parse_skill_markdown(text: str) -> Dict[str, str]:
    """Extract name/description from SKILL.md YAML frontmatter plus the body."""
    name = ""
    description = ""
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            frontmatter_raw = parts[1]
            body = parts[2].strip()
            try:
                import yaml

                fm = yaml.safe_load(frontmatter_raw) or {}
                if isinstance(fm, dict):
                    name = str(fm.get("name") or "").strip()
                    description = str(fm.get("description") or "").strip()
            except Exception as e:
                print(f"Warning: could not parse skill frontmatter as YAML: {e}")
    return {"name": name, "description": description, "body": body}


def extract_skill_content(filename: str, raw: bytes) -> str:
    """Return the SKILL.md text from an uploaded .md/.txt file or a .zip bundle."""
    lower = (filename or "").lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            candidates = [n for n in zf.namelist() if n.split("/")[-1].upper() == "SKILL.MD"]
            if not candidates:
                candidates = [n for n in zf.namelist() if n.lower().endswith(".md")]
            if not candidates:
                raise ValueError("Zip archive does not contain a SKILL.md (or any markdown) file.")
            # Prefer the shallowest SKILL.md (the skill root).
            candidates.sort(key=lambda n: n.count("/"))
            return zf.read(candidates[0]).decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def normalize_skill(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce an arbitrary incoming dict into a fully-formed skill config."""
    assignments = [a for a in (raw.get("assignments") or []) if a in VALID_SLOT_IDS]
    skill_id = raw.get("id") or uuid.uuid4().hex[:12]
    return {
        "id": skill_id,
        "name": (raw.get("name") or "Unnamed Skill").strip(),
        "description": (raw.get("description") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "content": raw.get("content") or "",
        "filename": (raw.get("filename") or "").strip(),
        "assignments": assignments,
        "updated_at": float(raw.get("updated_at") or time.time()),
        # Disk-discovered skills (skills_dir) are read-only: the file is the
        # source of truth for content; only assignments/enabled live in the DB.
        "source": "disk" if str(skill_id).startswith("disk_") else "upload",
    }


class SkillStore:
    """Persist uploaded Claude Skills in LanceDB (plain JSON blobs, no secrets)."""

    def __init__(self):
        self._db_conn = None
        self._table = None
        self.table_name = "skills"
        self._cache: Dict[str, Dict[str, Any]] = {}
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
                    [
                        pa.field("id", pa.string(), nullable=False),
                        pa.field("blob", pa.string(), nullable=False),
                    ]
                )
                self._table = conn.create_table(self.table_name, schema=schema)
        return self._table

    def load_all(self):
        self._cache = {}
        try:
            records = self.table.search().limit(1000).to_list()
            for r in records:
                blob = r.get("blob")
                if not blob:
                    continue
                try:
                    data = json.loads(blob)
                    if data and data.get("id"):
                        self._cache[data["id"]] = normalize_skill(data)
                except Exception as e:
                    print(f"Warning: could not decode skill row {r.get('id')}: {e}")
        except Exception as e:
            print(f"Warning: could not load skills from LanceDB: {e}")

        # Discover skills from config.skills_dir if configured and exists
        try:
            skills_dir = getattr(config, "skills_dir", None)
            if skills_dir and os.path.isdir(skills_dir):
                from pathlib import Path
                dir_path = Path(skills_dir)
                discovered_disk_ids = set()
                for child in dir_path.iterdir():
                    skill_content = None
                    filename = child.name
                    skill_name_derived = child.name

                    if child.is_dir():
                        # Look for SKILL.md in directory
                        for subchild in child.iterdir():
                            if subchild.is_file() and subchild.name.upper() == "SKILL.MD":
                                try:
                                    skill_content = subchild.read_text(encoding="utf-8", errors="replace")
                                except Exception as err:
                                    print(f"Warning: could not read skill file '{subchild}': {err}")
                                break
                    elif child.is_file() and child.suffix.lower() == ".md":
                        try:
                            skill_content = child.read_text(encoding="utf-8", errors="replace")
                        except Exception as err:
                            print(f"Warning: could not read skill file '{child}': {err}")
                        skill_name_derived = child.stem

                    if skill_content is not None:
                        parsed = parse_skill_markdown(skill_content)
                        # Derive a stable ID
                        stable_id = f"disk_{skill_name_derived.lower()}"
                        discovered_disk_ids.add(stable_id)

                        # Merge with database configuration if it exists to preserve assignments and enabled toggles
                        existing = self._cache.get(stable_id)

                        cfg = {
                            "id": stable_id,
                            "name": parsed["name"] or (existing.get("name") if existing else skill_name_derived),
                            "description": parsed["description"] or (existing.get("description") if existing else ""),
                            "enabled": existing.get("enabled", True) if existing else True,
                            "content": skill_content,
                            "filename": filename,
                            "assignments": existing.get("assignments", []) if existing else [],
                            "updated_at": os.path.getmtime(child) if hasattr(os, "getmtime") else time.time(),
                        }

                        self._cache[stable_id] = normalize_skill(cfg)

                # Remove disk-prefixed cache entries that are no longer present on
                # disk, including their persisted override rows so renamed/removed
                # files do not leave stale configuration behind.
                for key in list(self._cache.keys()):
                    if key.startswith("disk_") and key not in discovered_disk_ids:
                        self._cache.pop(key, None)
                        try:
                            self.table.delete(f"id = '{key}'")
                        except Exception:
                            pass
        except Exception as e:
            print(f"Warning: could not load skills from skills_dir: {e}")

    def list(self) -> List[Dict[str, Any]]:
        skills = [dict(v) for v in self._cache.values()]
        skills.sort(key=lambda s: s.get("name", "").lower())
        return skills

    def get(self, skill_id: str) -> Optional[Dict[str, Any]]:
        cfg = self._cache.get(skill_id)
        return dict(cfg) if cfg else None

    def save(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_skill(raw)
        # Metadata-only updates (toggle/assignments) keep the stored content.
        existing = self._cache.get(cfg["id"])
        if existing and not cfg.get("content"):
            cfg["content"] = existing.get("content", "")
        cfg["updated_at"] = time.time()
        self._cache[cfg["id"]] = cfg
        try:
            blob = json.dumps(cfg, ensure_ascii=False)
            tbl = self.table
            try:
                tbl.delete(f"id = '{cfg['id']}'")
            except Exception:
                pass
            tbl.add([{"id": cfg["id"], "blob": blob}])
        except Exception as e:
            print(f"Error persisting skill '{cfg['id']}': {e}")
        return cfg

    def save_upload(self, filename: str, content_base64: str, skill_id: Optional[str] = None) -> Dict[str, Any]:
        """Create or replace a skill from an uploaded file (base64-encoded)."""
        raw = base64.b64decode(content_base64)
        content = extract_skill_content(filename, raw)
        parsed = parse_skill_markdown(content)
        existing = self.get(skill_id) if skill_id else None
        cfg = {
            "id": skill_id or None,
            "name": parsed["name"] or (existing or {}).get("name") or filename.rsplit(".", 1)[0],
            "description": parsed["description"] or (existing or {}).get("description", ""),
            "enabled": (existing or {}).get("enabled", True),
            "content": content,
            "filename": filename,
            "assignments": (existing or {}).get("assignments", []),
        }
        return self.save(cfg)

    def delete(self, skill_id: str) -> bool:
        """Delete an uploaded skill's row and cache entry.

        For disk-discovered skills this only clears the persisted overrides
        (assignments/enabled); the skill reappears from disk on the next
        reload. The API layer blocks deleting disk skills for that reason.
        """
        existed = skill_id in self._cache
        self._cache.pop(skill_id, None)
        try:
            self.table.delete(f"id = '{skill_id}'")
        except Exception as e:
            print(f"Error deleting skill '{skill_id}': {e}")
        return existed

    # -- slot routing --------------------------------------------------------
    def skills_for_slot(self, slot: str) -> List[Dict[str, Any]]:
        return [s for s in self.list() if s.get("enabled", True) and slot in (s.get("assignments") or [])]


def skills_context_for_slot(slot: str, max_chars_per_skill: int = MAX_SKILL_CHARS) -> str:
    """Build the skill-guidance prompt block for a pipeline/agent slot.

    Returns an empty string when no enabled skill is assigned to ``slot`` (the
    common case), guaranteeing zero prompt overhead otherwise. Never raises.
    """
    try:
        skills = skill_store.skills_for_slot(slot)
        if not skills:
            return ""
        blocks: List[str] = []
        for s in skills:
            body = parse_skill_markdown(s.get("content", "")).get("body", "").strip()
            if not body:
                continue
            if len(body) > max_chars_per_skill:
                body = body[:max_chars_per_skill] + "\n[... skill instructions truncated ...]"
            header = f"[Skill: {s['name']}]"
            if s.get("description"):
                header += f" — {s['description']}"
            blocks.append(f"{header}\n{body}")
        if not blocks:
            return ""
        return (
            "SKILL GUIDANCE (user-installed expert instructions; apply them when analyzing, "
            "tagging and classifying):\n" + "\n\n".join(blocks) + "\n\n"
        )
    except Exception as e:
        print(f"[Skills] Failed to build skill context for slot '{slot}': {e}")
        return ""


skill_store = SkillStore()
