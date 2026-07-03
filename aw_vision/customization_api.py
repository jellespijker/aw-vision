"""API routes for pipeline customization: editable prompts and Claude Skills.

Kept out of ``server.py`` (per AGENTS.md decomposed-file budgets) as a FastAPI
router that the main app includes.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class PromptUpdateRequest(BaseModel):
    template: str


class SkillModel(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    enabled: bool = True
    content: Optional[str] = None
    filename: Optional[str] = ""
    assignments: Optional[List[str]] = None


class SkillUploadRequest(BaseModel):
    filename: str
    content_base64: str
    skill_id: Optional[str] = None


class PromptEvalRequest(BaseModel):
    template: str
    sample_size: int = 5


# ---------------------------------------------------------
# Pipeline Prompt Endpoints
# ---------------------------------------------------------


@router.get("/prompts")
def list_prompts():
    """List all pipeline prompt templates (active template, default and customization state)."""
    from aw_vision.prompts import prompt_store

    return {"prompts": prompt_store.list()}


@router.post("/prompts/{prompt_id}")
def update_prompt(prompt_id: str, payload: PromptUpdateRequest):
    """Save a customized template for a pipeline prompt."""
    from aw_vision.prompts import prompt_store

    try:
        prompt_store.set(prompt_id, payload.template)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "prompts": prompt_store.list()}


@router.post("/prompts/{prompt_id}/reset")
def reset_prompt(prompt_id: str):
    """Reset a pipeline prompt back to its built-in default template."""
    from aw_vision.prompts import prompt_store

    try:
        prompt_store.reset(prompt_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "prompts": prompt_store.list()}


# ---------------------------------------------------------
# Prompt Evaluation Endpoints
# ---------------------------------------------------------


@router.get("/prompts/eval/status")
def get_prompt_eval_status():
    """Status and per-record results of the active (or last) prompt evaluation."""
    from aw_vision.prompt_eval import prompt_evaluator

    return prompt_evaluator.status


@router.post("/prompts/{prompt_id}/eval")
def start_prompt_eval(prompt_id: str, payload: PromptEvalRequest):
    """Evaluate a candidate classification template against human-verified labels (background job)."""
    from aw_vision.prompt_eval import prompt_evaluator

    try:
        status = prompt_evaluator.start(prompt_id, payload.template, sample_size=payload.sample_size)
        return {"status": "started", "eval": status}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------
# Claude Skills Endpoints
# ---------------------------------------------------------


@router.get("/skills")
def list_skills():
    """List all uploaded Claude Skills with their prompt-slot assignments."""
    from aw_vision.skills import skill_store

    return {"skills": skill_store.list()}


@router.post("/skills")
def save_skill(payload: SkillModel):
    """Create or update a Claude Skill (metadata, assignments, enabled state, or inline content)."""
    from aw_vision.skills import skill_store

    try:
        saved = skill_store.save(payload.dict(exclude_none=False))
        return {"status": "success", "skill": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save skill: {e}")


@router.post("/skills/upload")
def upload_skill(payload: SkillUploadRequest):
    """Upload a Claude Skill file (SKILL.md markdown, or a .zip bundle containing one)."""
    from aw_vision.skills import skill_store

    if payload.skill_id and str(payload.skill_id).startswith("disk_"):
        raise HTTPException(
            status_code=400,
            detail="Disk-discovered skills are read-only here; edit the file in the skills directory instead.",
        )
    try:
        saved = skill_store.save_upload(payload.filename, payload.content_base64, skill_id=payload.skill_id)
        return {"status": "success", "skill": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to upload skill: {e}")


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str):
    """Delete an uploaded Claude Skill (disk-discovered skills are managed on disk)."""
    from aw_vision.config import config
    from aw_vision.skills import skill_store

    existing = skill_store.get(skill_id)
    if existing and existing.get("source") == "disk":
        raise HTTPException(
            status_code=400,
            detail=(
                "This skill is auto-discovered from the skills directory and would reappear "
                f"on reload. Remove its file from '{config.skills_dir}' instead."
            ),
        )
    existed = skill_store.delete(skill_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Skill not found.")
    return {"status": "success", "message": f"Deleted skill '{skill_id}'."}
