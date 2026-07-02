"""Tests for the pipeline customization layer: prompts, skills and rendering."""

import base64
import io
import os
import zipfile

# Isolate LanceDB writes before any aw_vision import (same pattern as test_backend).
os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision import skills as skills_mod  # noqa: E402
from aw_vision.prompts import PROMPT_DEFS, PromptStore, build_user_context_block, render_prompt  # noqa: E402
from aw_vision.skills import SkillStore, extract_skill_content, parse_skill_markdown  # noqa: E402

SKILL_MD = """---
name: Project Classifier Pro
description: Expert rules for mapping screenshots to projects.
---
# Classification rules
- Cura windows containing 'CuraEngine' map to project 100.
"""


def test_prompt_store_defaults_and_overrides():
    ps = PromptStore()
    ids = {p["id"] for p in ps.list()}
    assert ids == {d["id"] for d in PROMPT_DEFS}
    assert all(not p["is_customized"] for p in ps.list())

    ps.set("local_synthesis", "Custom template {projects} {existing_tags}")
    assert ps.get("local_synthesis").startswith("Custom template")
    entry = next(p for p in ps.list() if p["id"] == "local_synthesis")
    assert entry["is_customized"]

    # Persistence survives a fresh store instance
    assert PromptStore().get("local_synthesis").startswith("Custom template")

    # Saving the exact default (or empty) acts as a reset
    ps.reset("local_synthesis")
    entry = next(p for p in ps.list() if p["id"] == "local_synthesis")
    assert not entry["is_customized"]
    assert entry["template"] == entry["default_template"]


def test_render_prompt_preserves_json_braces():
    ps = PromptStore()
    mapping = {ph: f"<{ph}>" for ph in next(d for d in PROMPT_DEFS if d["id"] == "local_synthesis")["placeholders"]}
    mapping["user_context_block"] = build_user_context_block("Working on PRJ-2026-042 linting")
    rendered = render_prompt(ps.get("local_synthesis"), mapping)

    # All declared placeholders substituted; JSON schema braces untouched.
    for ph in mapping:
        assert "{" + ph + "}" not in rendered
    assert '"project_reasoning": "string"' in rendered
    assert "PRJ-2026-042 linting" in rendered
    assert "USER-PROVIDED CONTEXT" in rendered


def test_skill_markdown_parsing_and_zip_extraction():
    parsed = parse_skill_markdown(SKILL_MD)
    assert parsed["name"] == "Project Classifier Pro"
    assert parsed["description"].startswith("Expert rules")
    assert "Classification rules" in parsed["body"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-skill/SKILL.md", SKILL_MD)
        zf.writestr("my-skill/scripts/helper.py", "print('x')")
    content = extract_skill_content("my-skill.zip", buf.getvalue())
    assert "Classification rules" in content


def test_skill_store_crud_and_slot_injection():
    ss = SkillStore()
    # Clean any leftovers from previous runs
    for s in ss.list():
        ss.delete(s["id"])

    saved = ss.save_upload("SKILL.md", base64.b64encode(SKILL_MD.encode()).decode())
    try:
        assert saved["name"] == "Project Classifier Pro"

        saved["assignments"] = ["local_synthesis", "agent"]
        ss.save(saved)

        # Route the module-level helper through this store for the assertion.
        original = skills_mod.skill_store
        skills_mod.skill_store = ss
        try:
            block = skills_mod.skills_context_for_slot("local_synthesis")
            assert "SKILL GUIDANCE" in block and "CuraEngine" in block
            assert skills_mod.skills_context_for_slot("local_vision") == ""

            saved["enabled"] = False
            ss.save(saved)
            assert skills_mod.skills_context_for_slot("local_synthesis") == ""
        finally:
            skills_mod.skill_store = original

        # Metadata-only save keeps stored content
        meta_only = {k: (None if k == "content" else v) for k, v in saved.items()}
        assert "Classification rules" in ss.save(meta_only)["content"]
    finally:
        assert ss.delete(saved["id"])
        assert ss.list() == []
