"""Editable pipeline prompt templates.

Every LLM prompt used by the ingestion pipeline is defined here as a named,
user-editable template. Defaults live in code; user overrides are persisted in
LanceDB (plain text) and can be reset per prompt from the Settings UI.

Templates use single-brace ``{placeholder}`` tokens that are substituted with
:func:`render_prompt`. Unlike ``str.format`` this only replaces the known
placeholders of each prompt, so literal braces (e.g. JSON schemas) need no
escaping and a user typo can never raise a KeyError mid-pipeline.
"""

from typing import Any, Dict, List, Optional

from aw_vision.config import config

# ---------------------------------------------------------------------------
# Shared context-block builders
# ---------------------------------------------------------------------------


def build_user_context_block(user_context: Optional[str]) -> str:
    """Format the per-screenshot note the user wrote about what they were doing."""
    if not user_context or not user_context.strip():
        return ""
    return (
        "USER-PROVIDED CONTEXT (authoritative): the user personally wrote this note describing "
        "what was actually being worked on in this screenshot. Treat it as the highest-authority "
        "evidence for interpretation and project classification:\n"
        f'"""{user_context.strip()}"""\n\n'
    )


def build_mcp_context_block(mcp_context: Optional[str]) -> str:
    if not mcp_context or not mcp_context.strip():
        return ""
    return (
        "External MCP Tool Context (authoritative supplementary data from connected integrations "
        f"such as GitHub/Jira; use it to improve project classification and tags):\n{mcp_context.strip()}\n\n"
    )


GROUNDING_RULES = """GROUNDING RULES (apply to every output field):
- Be specific and evidence-based. Name the exact artifacts visible on screen: file names, directory paths, function/class names, git branch names, ticket IDs (e.g. PRJ-2026-042, EMB-467), URLs, document titles, terminal commands, spreadsheet tab names, chat participants.
- NEVER write generic filler such as "working on code", "a code editor is open", "browsing the web", "several windows are visible". If you can read it, name it; if you cannot read it, omit it rather than guessing.
- Prefer concrete nouns over activity categories: "editing aw_vision/server.py, function get_history()" beats "software development".
- Report only what is actually legible. Never invent, autocomplete, or "repair" truncated text, URLs, or identifiers.
- Describe content, not window chrome: skip title bars, scrollbars, docks, and OS decorations unless they carry unique information.
- If the screen shows a lock screen, screensaver, blank desktop, or paused media with no work content, state that plainly instead of inventing activity.
- When a user-provided context note is present, it is the highest authority on what was actually being worked on. Use it to disambiguate, but still report what is objectively visible."""


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

_GEMINI_OCR_DEFAULT = """Extract all readable text, titles, labels, browser URLs, files, or characters shown on this desktop screenshot exactly as shown. Do not explain, describe, or add any meta-commentary. Just output the extracted text."""


_GEMINI_COMBINED_DEFAULT = (
    """You are an expert desktop-activity analyst indexing a screenshot for a searchable work journal. The FIRST attached image is the focused foreground window crop; the SECOND (if present) is the full desktop context.

OS window metadata for this capture: application "{app_name}", window title "{window_title}". Use it to anchor your analysis, but trust the pixels when they disagree.

{user_context_block}{mcp_context_block}{skills_block}"""
    + GROUNDING_RULES
    + """

HISTORICAL & TEMPORAL CONTEXT (previously processed snapshots from the local database; use it to disambiguate ambiguous screens and keep classification, terminology and tags consistent over time — it is supporting evidence, the pixels remain primary):
- ActivityWatch Bucket State: {aw_context}
- Neighboring Snapshots: {neighbor_context}
- Historically Similar Snapshots: {similar_snapshots}
- App project statistics: {app_frequencies}

Perform the following tasks:
1. OCR ('ocr_text'): {ocr_instruction}
2. Foreground analysis ('active_window_description'): Describe precisely what application, document, URL, code, or workspace section the focused crop shows. Lead with the concrete subject (file, ticket, page, conversation), then the action in progress (editing, reviewing, debugging, reading, composing).
3. Peripheral analysis ('full_desktop_description'): Describe background or accessory windows OUTSIDE the focused area. Name them concretely; keep brief if there are none.
4. Unique artifacts ('unique_things'): List specific terminal commands, active code blocks, file paths, specialized charts, or unique widgets present on screen.
5. Classification reasoning ('project_reasoning'): Reason step by step IN THIS FIELD before deciding on a project. Keep it terse — evidence fragments, not prose, under ~120 words:
   a. List the strongest pieces of evidence (identifiers, paths, ticket prefixes, repository names, the window metadata, user-provided context).
   b. Name the matching catalog candidates and the ruled-out near-misses, each with its deciding evidence.
   c. Weigh continuity: neighboring and human-verified snapshots on the same application forming a continuous block of activity are strong evidence.
   d. Conclude whether the best match is DIRECT (explicit identifier/description overlap) or merely THEMATIC. Only a direct match justifies classification.
6. Match type ('match_type'): Output exactly one of "direct", "thematic", or "none" — the conclusion of your reasoning above.
7. Project classification ('project_number'): Based ONLY on your reasoning above, output the single best catalog project number, or "None" when the evidence is thematic, indirect, or ambiguous. Do NOT match on inactive sidebar chats, adjacent tab names, browser bookmarks, or company names alone. Stay consistent with the user-provided context note when present.
8. Technical tags ('tags'): Generate 3 to 7 highly relevant, technical tags. Reuse these existing database tags VERBATIM when they apply: [{existing_tags}]. New tags must be short technical noun phrases (1-3 words); never emit near-synonyms of an existing tag.
9. Synthesis ('description'): One ultra-dense, technical "Caveman-style" summary of at most ~50 words. Speak in fragments, use semicolons, omit filler words (the, a, is, was, were, to, of, for). Every concrete identifier from the evidence (files, functions, tickets, URLs) must survive into it verbatim.
   Example: "Dev aw-vision UI. Refactored GalleryTab.tsx list component; unique elements via exact CSS tokens; PR #22 review."

Project Reference Catalog:
{projects}

You must respond in valid JSON format matching this exact schema (keep the key order — reasoning comes before the decision):
{
  "ocr_text": "string",
  "active_window_description": "string",
  "full_desktop_description": "string",
  "unique_things": "string",
  "project_reasoning": "string",
  "match_type": "direct | thematic | none",
  "project_number": "string",
  "tags": ["string"],
  "description": "string"
}"""
)


_LOCAL_VISION_DEFAULT = (
    """Analyze the attached desktop screenshot(s). {image_layout_note}

OS window metadata for this capture: application "{app_name}", window title "{window_title}". Use it to anchor your analysis, but trust the pixels when they disagree.

{previous_snapshot_block}{user_context_block}{mcp_context_block}{skills_block}"""
    + GROUNDING_RULES
    + """

You must respond in valid JSON format matching this schema:
{
  "active_window_description": "what the focused foreground window/document/workspace shows — lead with the concrete subject (file, ticket, URL, conversation), then the action in progress",
  "full_desktop_description": "peripheral/background windows, sidebars or layout OUTSIDE the focus, named concretely (keep brief if none)",
  "unique_things": "specific terminal commands, active code blocks, file paths, specialized widgets or tools present"
}"""
)


_LOCAL_SYNTHESIS_DEFAULT = """You are indexing a desktop snapshot for a searchable work journal. Use ONLY the evidence below.

{user_context_block}- Application (from OS metadata): {app_name}
- Window Title (from OS metadata): {window_title}
- Active Window: {active_window_description}
- Desktop Context: {full_desktop_description}
- Unique Artifacts: {unique_things}
- Extracted Screen Text (OCR): {ocr_text}
- ActivityWatch Bucket State: {aw_context}
- Neighboring Snapshots: {neighbor_context}
- Historically Similar Snapshots: {similar_snapshots}
- App project statistics: {app_frequencies}
{mcp_context_block}{skills_block}
Project Reference Catalog:
{projects}

Produce exactly five outputs, in this order:
1. project_reasoning: Reason step by step BEFORE deciding. Keep it terse — evidence fragments, not prose, under ~120 words:
   a. List the strongest pieces of evidence (identifiers, file paths, ticket prefixes, repository names, the window title, the user-provided context note when present).
   b. Name the matching catalog candidates and the ruled-out near-misses, each with its deciding evidence.
   c. Weigh continuity: neighboring and human-verified snapshots on the same application forming a continuous block of activity are strong evidence.
   d. Conclude whether the best match is DIRECT (explicit identifier/description overlap) or merely THEMATIC.
2. match_type: Output exactly one of "direct", "thematic", or "none" — the conclusion of your reasoning above.
3. project_number: Based ONLY on the reasoning above, classify this activity into ONE catalog project. Be conservative: if there is no direct, explicit link between the active screen contents and a project's description/entailment, output "None". Do NOT match on inactive sidebar chats, adjacent tab names, browser bookmarks, or external company profiles. If the screen shows a lock screen, blank desktop, or idle content, output "None".
4. tags: 3 to 7 highly relevant, technical tags/keywords for this task. Reuse these existing database tags VERBATIM when they apply: {existing_tags}. New tags must be short technical noun phrases (1-3 words); never emit near-synonyms of an existing tag.
5. description: An ultra-dense, highly precise "Caveman-style" work summary of at most ~50 words. Omit filler words (the, a, is, was, were, to, of, for); use dense technical fragments separated by semicolons/periods. Every concrete identifier from the evidence (file names, functions, URLs, tickets) must survive into it verbatim — never replace them with generic activity words.
   Example: "Dev aw-vision UI. Refactored GalleryTab.tsx list component; unique elements via exact CSS tokens; PR #22 review."

You must respond in valid JSON format matching this exact schema (keep the key order — reasoning comes before the decision):
{
  "project_reasoning": "string",
  "match_type": "direct | thematic | none",
  "project_number": "string (catalog project number, or \\"None\\")",
  "tags": ["string"],
  "description": "string"
}"""


PROMPT_DEFS: List[Dict[str, Any]] = [
    {
        "id": "gemini_ocr",
        "label": "Gemini OCR",
        "group": "Cloud Pipeline",
        "description": "Standalone cloud OCR extraction pass (used when the OCR provider is Gemini but the vision pass is not combined).",
        "placeholders": [],
        "default": _GEMINI_OCR_DEFAULT,
    },
    {
        "id": "gemini_combined",
        "label": "Gemini Combined OCR + Vision",
        "group": "Cloud Pipeline",
        "description": "Single multimodal cloud call performing OCR, foreground/background analysis, project classification with explicit reasoning, tags and the caveman summary.",
        "placeholders": [
            "app_name",
            "window_title",
            "user_context_block",
            "mcp_context_block",
            "skills_block",
            "aw_context",
            "neighbor_context",
            "similar_snapshots",
            "app_frequencies",
            "ocr_instruction",
            "projects",
            "existing_tags",
        ],
        "default": _GEMINI_COMBINED_DEFAULT,
    },
    {
        "id": "local_vision",
        "label": "Local Vision Pass (window · desktop · artifacts)",
        "group": "Local Pipeline",
        "description": "Local multimodal pass describing the focused window, peripheral desktop and unique artifacts.",
        "placeholders": [
            "image_layout_note",
            "app_name",
            "window_title",
            "previous_snapshot_block",
            "user_context_block",
            "mcp_context_block",
            "skills_block",
        ],
        "default": _LOCAL_VISION_DEFAULT,
    },
    {
        "id": "local_synthesis",
        "label": "Local Synthesis (classification · tags · description)",
        "group": "Local Pipeline",
        "description": "Text-only pass that reasons about project classification, generates tags and synthesizes the dense description from all gathered evidence.",
        "placeholders": [
            "user_context_block",
            "app_name",
            "window_title",
            "active_window_description",
            "full_desktop_description",
            "unique_things",
            "ocr_text",
            "aw_context",
            "neighbor_context",
            "similar_snapshots",
            "app_frequencies",
            "mcp_context_block",
            "skills_block",
            "projects",
            "existing_tags",
        ],
        "default": _LOCAL_SYNTHESIS_DEFAULT,
    },
]

_DEFS_BY_ID = {d["id"]: d for d in PROMPT_DEFS}
VALID_PROMPT_IDS = set(_DEFS_BY_ID.keys())


def render_prompt(template: str, mapping: Dict[str, Any]) -> str:
    """Substitute known ``{placeholder}`` tokens; leave all other braces untouched."""
    out = template
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    return out


class PromptStore:
    """Persist user-customized prompt templates in LanceDB (plain text)."""

    def __init__(self):
        self._db_conn = None
        self._table = None
        self.table_name = "prompts"
        self._overrides: Dict[str, str] = {}
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
        self._overrides = {}
        try:
            records = self.table.search().limit(100).to_list()
            for r in records:
                k = r.get("key")
                v = r.get("value")
                if k in VALID_PROMPT_IDS and v:
                    self._overrides[k] = v
        except Exception as e:
            print(f"Warning: Could not load prompt overrides from LanceDB, using defaults. Error: {e}")

    def get(self, prompt_id: str) -> str:
        """Return the active template for a prompt (user override or code default)."""
        override = self._overrides.get(prompt_id)
        if override:
            return override
        d = _DEFS_BY_ID.get(prompt_id)
        return d["default"] if d else ""

    def set(self, prompt_id: str, template: str):
        if prompt_id not in VALID_PROMPT_IDS:
            raise ValueError(f"Unknown prompt id '{prompt_id}'.")
        template = (template or "").strip()
        default = _DEFS_BY_ID[prompt_id]["default"]
        if not template or template == default.strip():
            # Saving empty or an exact default acts as a reset.
            self.reset(prompt_id)
            return
        self._overrides[prompt_id] = template
        try:
            tbl = self.table
            try:
                tbl.delete(f"key = '{prompt_id}'")
            except Exception:
                pass
            tbl.add([{"key": prompt_id, "value": template}])
        except Exception as e:
            print(f"Error persisting prompt '{prompt_id}' to database: {e}")

    def reset(self, prompt_id: str):
        if prompt_id not in VALID_PROMPT_IDS:
            raise ValueError(f"Unknown prompt id '{prompt_id}'.")
        self._overrides.pop(prompt_id, None)
        try:
            self.table.delete(f"key = '{prompt_id}'")
        except Exception as e:
            print(f"Error deleting prompt override '{prompt_id}': {e}")

    def list(self) -> List[Dict[str, Any]]:
        """Full prompt catalog for the Settings UI."""
        out = []
        for d in PROMPT_DEFS:
            pid = d["id"]
            out.append(
                {
                    "id": pid,
                    "label": d["label"],
                    "group": d["group"],
                    "description": d["description"],
                    "placeholders": d["placeholders"],
                    "template": self.get(pid),
                    "default_template": d["default"],
                    "is_customized": pid in self._overrides,
                }
            )
        return out


prompt_store = PromptStore()
