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


def _uploaded(ss):
    """Only upload-sourced skills; the machine's skills_dir may hold real disk skills."""
    return [s for s in ss.list() if s.get("source") != "disk"]


def test_skill_store_crud_and_slot_injection():
    ss = SkillStore()
    # Clean any uploaded leftovers from previous runs
    for s in _uploaded(ss):
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
        assert _uploaded(ss) == []


def test_skills_dir_auto_discovery():
    import tempfile
    from pathlib import Path

    # Clean any uploaded LanceDB leftovers
    ss = SkillStore()
    for s in _uploaded(ss):
        ss.delete(s["id"])

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Create a file-based skill
        file_skill_md = """---
name: Disk Skill One
description: A direct file skill on disk.
---
# Instructions One
- Step 1: Do something.
"""
        file_skill_path = tmp_path / "one_skill.md"
        file_skill_path.write_text(file_skill_md, encoding="utf-8")

        # 2. Create a directory-based skill bundle
        dir_skill_md = """---
name: Disk Skill Two
description: A directory skill bundle on disk.
---
# Instructions Two
- Step 2: Do another thing.
"""
        bundle_dir = tmp_path / "two_skill_dir"
        bundle_dir.mkdir()
        skill_md_path = bundle_dir / "SKILL.md"
        skill_md_path.write_text(dir_skill_md, encoding="utf-8")

        # Mock config.settings["customization"]
        old_custom = skills_mod.config.settings.get("customization")
        skills_mod.config.settings["customization"] = {"skills_dir": str(tmp_path)}

        try:
            # Reload from store (which triggers load_all)
            ss.load_all()

            # Verify both skills are loaded
            one = ss.get("disk_one_skill")
            two = ss.get("disk_two_skill_dir")

            assert one is not None
            assert two is not None
            assert one["name"] == "Disk Skill One"
            assert "Instructions One" in one["content"]
            assert two["name"] == "Disk Skill Two"
            assert "Instructions Two" in two["content"]
            assert one["enabled"] is True

            # Verify LanceDB state merging (assignments & toggle)
            # Simulate editing and saving one skill in the UI
            one["assignments"] = ["agent"]
            one["enabled"] = False
            ss.save(one)

            # Trigger reload to simulate a restart
            ss.load_all()
            reloaded_one = ss.get("disk_one_skill")
            assert reloaded_one is not None
            assert reloaded_one["enabled"] is False
            assert reloaded_one["assignments"] == ["agent"]
            # Still has the content loaded from disk
            assert "Instructions One" in reloaded_one["content"]

            # 3. Test self-cleaning prune on deletion/rename
            # Delete 'one_skill.md' from disk
            file_skill_path.unlink()

            # Trigger reload - 'disk_one_skill' should be pruned from cache
            ss.load_all()
            assert ss.get("disk_one_skill") is None
            assert ss.get("disk_two_skill_dir") is not None

        finally:
            # Restore config
            if old_custom is None:
                skills_mod.config.settings.pop("customization", None)
            else:
                skills_mod.config.settings["customization"] = old_custom
            # Clean up saved LanceDB state for disk_one_skill and disk_two_skill_dir
            ss.delete("disk_one_skill")
            ss.delete("disk_two_skill_dir")


def test_progressive_skill_disclosure_switches_to_index_mode():
    ss = SkillStore()
    for s in _uploaded(ss):
        ss.delete(s["id"])

    original = skills_mod.skill_store
    skills_mod.skill_store = ss
    created = []
    try:
        # Up to FULL_INJECT_MAX skills: full bodies injected, no read_skill tool.
        for i in range(skills_mod.FULL_INJECT_MAX):
            md = f"---\nname: Full Skill {i}\ndescription: D{i}\n---\nBody {i} instructions."
            saved = ss.save_upload(f"full{i}.md", base64.b64encode(md.encode()).decode())
            saved["assignments"] = ["agent"]
            ss.save(saved)
            created.append(saved["id"])
        block = skills_mod.skills_context_for_slot("agent")
        assert "SKILL GUIDANCE" in block and "Body 0 instructions" in block
        assert skills_mod.skill_tools_for_slot("agent") == []

        # One more skill flips the slot into index mode with the read_skill tool.
        md = "---\nname: Overflow Skill\ndescription: Rules for overflow.\n---\nOverflow body text."
        saved = ss.save_upload("overflow.md", base64.b64encode(md.encode()).decode())
        saved["assignments"] = ["agent"]
        ss.save(saved)
        created.append(saved["id"])

        block = skills_mod.skills_context_for_slot("agent")
        assert "SKILL INDEX" in block
        assert "Overflow Skill: Rules for overflow." in block
        assert "Overflow body text" not in block  # bodies are NOT injected in index mode

        tools = skills_mod.skill_tools_for_slot("agent")
        assert len(tools) == 1 and tools[0].name == "read_skill"
        loaded = tools[0].run("overflow skill")  # case-insensitive exact name
        assert "Overflow body text" in loaded
        assert "no skill named" in tools[0].run("does-not-exist")
    finally:
        skills_mod.skill_store = original
        for sid in created:
            ss.delete(sid)
