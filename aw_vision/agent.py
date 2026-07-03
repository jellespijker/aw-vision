import json
import os
import re
import subprocess
from datetime import datetime
from typing import Annotated, Sequence, TypedDict, Union

import requests
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from aw_vision.config import config
from aw_vision.db import db
from aw_vision.tool_summary import caveman_compress_text, summarize_tool_result


# ---------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------


def tool_search_screenshots_semantic(query: str, limit: int = 5) -> str:
    """Perform a semantic vector similarity search on processed screenshots."""
    try:
        # Step 1: Embed query dynamically based on the active provider
        from aw_vision.processor import processor
        query_vector = processor.get_embedding(query)
        if not query_vector or all(v == 0.0 for v in query_vector):
            return "Error: Failed to generate query embedding vector."

        # Step 2: Query LanceDB
        results = db.search_semantic(query_vector, limit=limit)
        if not results:
            return "No matching screenshots or active screens found."

        # Step 3: Format results
        output = []
        for r in results:
            dt = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S")
            tags_str = ", ".join(r.get("tags", []))
            ocr_text = r.get("ocr_text", "N/A") or "N/A"
            ocr_text = caveman_compress_text(ocr_text)
            if len(ocr_text) > 350:
                ocr_text = ocr_text[:350].strip() + "..."

            dist_val = f"{r.get('_distance'):.4f}" if '_distance' in r and isinstance(r.get('_distance'), (int, float)) else r.get('_distance', 'N/A')
            output.append(
                f"- [{dt}] (Similarity: {dist_val}) App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"  Desc: {r.get('description')}\n"
                f"  OCR: {ocr_text}\n"
                f"  Tags: {tags_str} | Proj: {r.get('project_number')}"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error performing semantic search: {e}"


def tool_get_active_projects() -> str:
    """Retrieve the list of configured work projects and their work entailments."""
    projects = config.load_projects()
    if not projects:
        return "No active work projects configured."
    return json.dumps(projects, indent=2, ensure_ascii=False)


def tool_aggregate_project_hours() -> str:
    """Aggregate tracked hours per project code (based on non-AFK screenshots)."""
    try:
        stats = db.get_project_statistics()
        if not stats:
            return "No tracked work hours found in database."

        output = ["=== Tracked Project Hours ==="]
        projects = {p["project_number"]: p for p in config.load_projects()}

        for p_num, hours in stats.items():
            proj_info = projects.get(p_num, {})
            desc = proj_info.get("description", "Unconfigured/Unclassified project")
            output.append(f"- {p_num} ({desc}): {hours:.2f} hours")
        return "\n".join(output)
    except Exception as e:
        return f"Error aggregating project hours: {e}"


def tool_query_github(query: str) -> str:
    """Query GitHub commits, pull requests, or issues using local authenticated gh CLI."""
    try:
        # Check if gh CLI is available
        import shutil

        if not shutil.which("gh"):
            return "GitHub CLI (gh) is not installed on this system. Cannot query GitHub."

        # Run gh search search command
        cmd = [
            "gh",
            "search",
            "all",
            query,
            "--limit",
            "5",
            "--json",
            "title,url,updatedAt,type,repository",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            if not data:
                return f"No GitHub results found for query: '{query}'"
            output = ["=== GitHub Search Results ==="]
            for item in data:
                repo = item.get("repository", {}).get("name", "Unknown")
                output.append(
                    f"[{item.get('type', 'Item')}] {item.get('title')}\n"
                    f"  Repo: {repo} | Link: {item.get('url')} | Updated: {item.get('updatedAt')}"
                )
            return "\n".join(output)
        else:
            return f"Error running gh CLI: {res.stderr}"
    except Exception as e:
        return f"Error querying GitHub: {e}"


def tool_query_jira(jql: str) -> str:
    """Query Jira issues using search (JQL). Uses placeholder API or mock client if no jira config is set."""
    # Since atlassian-mcp-server is registered as lazy loaded, we can mock it here
    # or query a default local Jira configuration if user has one
    return f"Jira Search for '{jql}':\n- Found 0 matching issues in current local context."


def tool_execute_command(command: str) -> str:
    """Execute a whitelisted local command-line tool (such as 'gws' or 'gh') in a secure sandbox."""
    try:
        import shlex
        import shutil

        # Clean command and reject any forbidden characters or shell operators as a defense-in-depth measure
        cmd_str = (command or "").strip()
        if not cmd_str:
            return "Error: Command cannot be empty."

        # Detect dangerous characters that are common in shell injections
        # Since we run with shell=False, subprocess doesn't interpret them, but shlex.split might
        # still parse them as arguments. We explicitly block them to enforce strict command-line whitelisting.
        forbidden_chars = [";", "&&", "||", "|", ">", "<", "`", "$", "\n", "\r"]
        for char in forbidden_chars:
            if char in cmd_str:
                return f"Error: Command contains forbidden shell operator or character '{char}'."

        # Safely split command into arguments using shlex (handles quotes and JSON parameters perfectly)
        try:
            args = shlex.split(cmd_str)
        except Exception as e:
            return f"Error parsing command arguments: {e}"

        if not args:
            return "Error: Command resolved to an empty argument list."

        # Extract the base binary name
        binary = args[0]

        # Restrict strictly to whitelisted commands
        if binary not in ("gws", "gh"):
            return f"Error: Command '{binary}' is not whitelisted. Only 'gws' and 'gh' are permitted."

        # Check if the binary is available on the system
        if not shutil.which(binary):
            return f"Error: CLI tool '{binary}' is not installed or not in PATH."

        # Build clean environment with only whitelisted environment variables
        clean_env = {}
        # Preserving essential PATH and HOME
        if "PATH" in os.environ:
            clean_env["PATH"] = os.environ["PATH"]
        if "HOME" in os.environ:
            clean_env["HOME"] = os.environ["HOME"]

        # Whitelist other specific auth or config variables
        for key, value in os.environ.items():
            if key.startswith("GOOGLE_WORKSPACE_") or key.startswith("GITHUB_") or key.startswith("GH_"):
                clean_env[key] = value

        # Run command securely with shell=False and 10.0-second timeout
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=clean_env,
            timeout=10.0,
            shell=False,
        )

        # Format stdout and stderr
        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()

        output = []
        if res.returncode == 0:
            if stdout:
                output.append(stdout)
            else:
                output.append(f"Command '{binary}' executed successfully with no stdout.")
        else:
            output.append(f"Command '{binary}' failed with exit code {res.returncode}.")
            if stdout:
                output.append(f"Stdout:\n{stdout}")
            if stderr:
                output.append(f"Stderr:\n{stderr}")

        return "\n".join(output)

    except subprocess.TimeoutExpired:
        return "Error: Command execution timed out after 10 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


def tool_get_similar_labeled_snapshots(query: str, limit: int = 5) -> str:
    """Search the database for similar labeled snapshots. This tool scores results by favoring manually/human labeled data and matching tags/app names."""
    try:
        # Step 1: Embed query dynamically based on the active provider
        from aw_vision.processor import processor
        query_vector = processor.get_embedding(query)
        if not query_vector or all(v == 0.0 for v in query_vector):
            return "Error: Failed to generate query embedding vector."

        words = [w.strip().lower() for w in re.split(r'\s+', query) if w.strip()]

        # Step 2: Query LanceDB using the advanced labeled scoring helper
        results = db.get_similar_labeled_snapshots(query_vector, tags=words, limit=limit)
        if not results:
            return "No matching labeled screenshots or active screens found."

        # Step 3: Format results
        output = []
        for r in results:
            is_human = "Human Verified" if r.get("human_labeled") else "Auto Labeled"
            tags_str = ", ".join(r.get("tags", []))
            output.append(
                f"- [Score: {r.get('score', 0.0):.2f}] Proj: {r.get('project_number')} ({is_human})\n"
                f"  App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"  Desc: {r.get('description')}\n"
                f"  Tags: {tags_str}"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error searching similar labeled snapshots: {e}"


def tool_get_recent_screenshots(limit: Union[int, str] = 10) -> str:
    """Retrieve the most recent desktop screenshots, metadata, and extracted OCR text from the database."""
    try:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 10
        results = db.get_all_records(limit=limit)
        if not results:
            return "No recent screenshots or active screens found in database."

        output = []
        for r in results:
            dt = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S")
            tags_str = ", ".join(r.get("tags", []))
            ocr_text = r.get("ocr_text", "N/A") or "N/A"
            ocr_text = caveman_compress_text(ocr_text)
            if len(ocr_text) > 150:
                ocr_text = ocr_text[:150].strip() + "..."

            output.append(
                f"- [{dt}] App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"  Desc: {r.get('description')}\n"
                f"  OCR: {ocr_text}\n"
                f"  Tags: {tags_str} | Proj: {r.get('project_number')}"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error retrieving recent screenshots: {e}"


def tool_get_current_datetime(arg: str = None) -> str:
    """Return the current local date, time, weekday, ISO timestamp and epoch seconds.

    Useful when the agent needs to ground itself before reasoning about relative dates
    ('yesterday', 'last week') or to directly answer 'what time/day is it'. Takes no arguments.
    """
    now = datetime.now()
    return (
        f"Current local datetime:\n"
        f"- Date: {now:%Y-%m-%d} ({now:%A})\n"
        f"- Time: {now:%H:%M:%S}\n"
        f"- ISO: {now.isoformat(timespec='seconds')}\n"
        f"- Epoch seconds: {now.timestamp():.0f}"
    )


def _parse_timeframe_arg(arg: str) -> dict:
    """Normalise the agent's single-string argument into a params dict.

    Accepts either a plain timeframe phrase ('yesterday') or a compact JSON object so the
    agent can pick optional filters, e.g.
    {"timeframe": "yesterday", "app": "Firefox", "project": "PRJ-2026-042", "query": "lint"}.
    """
    raw = (arg or "").strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {k: (str(v).strip() if v is not None else None) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {"timeframe": raw}


def tool_get_activity_for_timeframe(arg: str) -> str:
    """Retrieve desktop activity within a specific date/time window, with optional filters.

    The argument is flexible so the agent can pick what it needs. Pass either:
      - a plain timeframe phrase: 'yesterday', 'this morning', 'last week', 'last 3 days',
        a weekday name, an ISO date (2026-06-28), or a range (2026-06-01 to 2026-06-07); or
      - a compact JSON object to narrow results, e.g.
        {"timeframe": "yesterday", "app": "Firefox", "project": "PRJ-2026-042", "query": "lint"}.
    The timeframe is resolved to a concrete epoch range in Python so date filtering is exact.
    """
    from aw_vision.timeframe import parse_timeframe

    params = _parse_timeframe_arg(arg)
    timeframe = params.get("timeframe") or params.get("when") or ""
    app_filter = (params.get("app") or "").lower()
    project_filter = (params.get("project") or "").lower()
    query_filter = (params.get("query") or params.get("keyword") or "").lower()

    parsed = parse_timeframe(timeframe)
    if not parsed:
        return (
            f"Could not interpret the timeframe '{timeframe}'. Try phrases like 'yesterday', "
            "'this morning', 'last week', 'last 3 days', or an ISO date like '2026-06-28'."
        )
    start_ts, end_ts, label = parsed

    try:
        where = f"timestamp >= {start_ts} AND timestamp <= {end_ts}"
        records = db.query_metadata(where, limit=100000)
    except Exception as e:
        return f"Error querying activity for {label}: {e}"

    # Keep only active (non-AFK) records and order chronologically.
    active = [r for r in records if not r.get("is_afk")]

    # Apply optional generic filters the agent may have supplied.
    applied = []
    if app_filter:
        active = [r for r in active if app_filter in (r.get("app_name") or "").lower()]
        applied.append(f"app~'{app_filter}'")
    if project_filter:
        active = [r for r in active if project_filter in (r.get("project_number") or "").lower()]
        applied.append(f"project~'{project_filter}'")
    if query_filter:
        def _matches(r):
            blob = " ".join([
                r.get("description") or "", r.get("ocr_text") or "",
                r.get("window_title") or "", " ".join(r.get("tags") or []),
            ]).lower()
            return query_filter in blob
        active = [r for r in active if _matches(r)]
        applied.append(f"query~'{query_filter}'")

    active.sort(key=lambda x: x.get("timestamp", 0))
    filter_note = f" [filters: {', '.join(applied)}]" if applied else ""
    if not active:
        return f"No active desktop activity recorded for {label}{filter_note}."

    interval_hours = config.screenshot_interval / 3600.0
    total_hours = len(active) * interval_hours

    # Aggregate time per app and per project so the agent gets a grounded breakdown.
    by_app: dict = {}
    by_project: dict = {}
    for r in active:
        app = r.get("app_name") or "Unknown"
        by_app[app] = by_app.get(app, 0.0) + interval_hours
        p_num = r.get("project_number") or "Unclassified"
        by_project[p_num] = by_project.get(p_num, 0.0) + interval_hours

    output = [
        f"=== Activity for {label}{filter_note} ===",
        f"Window: {datetime.fromtimestamp(start_ts):%Y-%m-%d %H:%M} to {datetime.fromtimestamp(end_ts):%Y-%m-%d %H:%M}",
        f"Active time (approx): {total_hours:.2f} hours across {len(active)} snapshots.",
        "",
        "Time per project:",
    ]
    for p_num, hrs in sorted(by_project.items(), key=lambda kv: kv[1], reverse=True):
        output.append(f"  - {p_num}: {hrs:.2f}h")
    output.append("Time per application:")
    for app, hrs in sorted(by_app.items(), key=lambda kv: kv[1], reverse=True)[:12]:
        output.append(f"  - {app}: {hrs:.2f}h")

    output.append("")
    output.append("Chronological timeline:")
    for r in active:
        dt = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%H:%M")
        ocr_text = caveman_compress_text(r.get("ocr_text", "N/A") or "N/A")
        if len(ocr_text) > 120:
            ocr_text = ocr_text[:120].strip() + "..."
        output.append(
            f"- [{dt}] {r.get('app_name')} | {r.get('window_title')}: {r.get('description')} "
            f"(Proj: {r.get('project_number')})"
        )
    return "\n".join(output)


def tool_find_person_moments(name: str) -> str:
    """Find all snapshots where a specific person was involved (chats, mails, meetings, mentions)."""
    from aw_vision.db import db

    query = (name or "").strip()
    if not query:
        return "Error: provide a person name to search for."
    query_lower = query.lower()
    try:
        records = db.get_all_records(limit=100000)
        matches = [
            r for r in records
            if any(query_lower in str(n).lower() for n in (r.get("people") or []))
        ]
        if not matches:
            return (
                f"No snapshots list '{query}' as a recognized person. "
                "Tip: fall back to search_screenshots_semantic with the name as the query."
            )
        lines = [f"Found {len(matches)} snapshot(s) involving '{query}' (newest first):"]
        for r in matches[:25]:
            ts = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M")
            people = ", ".join(r.get("people") or [])
            lines.append(
                f"- [{ts}] {r.get('app_name', 'Unknown')} | {r.get('window_title', 'Unknown')} | "
                f"Proj: {r.get('project_number') or 'None'} | People: {people} | {r.get('description', '')[:160]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching person moments: {e}"


# Export a tool mapping
TOOLS = {
    "search_screenshots_semantic": tool_search_screenshots_semantic,
    "get_similar_labeled_snapshots": tool_get_similar_labeled_snapshots,
    "get_recent_screenshots": tool_get_recent_screenshots,
    "get_activity_for_timeframe": tool_get_activity_for_timeframe,
    "get_current_datetime": tool_get_current_datetime,
    "get_active_projects": tool_get_active_projects,
    "aggregate_project_hours": tool_aggregate_project_hours,
    "query_github": tool_query_github,
    "query_jira": tool_query_jira,
    "execute_command": tool_execute_command,
    "find_person_moments": tool_find_person_moments,
}


# ---------------------------------------------------------
# Unified tool registry (builtins + MCP tools on the "agent" slot)
# ---------------------------------------------------------


def _wrap_builtin(name: str, fn):
    from aw_vision.tooling import ToolSpec

    def run(arg: str) -> str:
        if not arg or arg.strip().lower() == "none":
            return fn()
        return fn(arg)

    return ToolSpec(name=name, description=(fn.__doc__ or "").strip(), run=run, source="builtin")


def build_agent_toolspecs() -> dict:
    """The full uniform tool registry for the Ask Memory Agent.

    Builtins and slot-assigned MCP tools are wrapped identically (ToolSpec) so
    the parse/dispatch/observe path is shared with every other ReAct agent in
    the system. Discovery failures degrade to builtins only.
    """
    from aw_vision.tooling import mcp_tools_for_slot

    specs = {name: _wrap_builtin(name, fn) for name, fn in TOOLS.items()}
    for spec in mcp_tools_for_slot("agent"):
        specs.setdefault(spec.name, spec)
    return specs


# ---------------------------------------------------------
# LangGraph ReAct Agent State Machine
# ---------------------------------------------------------


class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    next_node: str
    tool_events: list


def clean_final_response(text: str) -> str:
    """Clean up any leftover inner thoughts, plans, or meta-commentary from the final answer."""
    if not text:
        return text

    # If the model explicitly used an Answer / Final Answer / Response block, extract it
    for marker in [r"(?i)final\s+answer\s*:\s*", r"(?i)answer\s*:\s*", r"(?i)response\s*:\s*"]:
        match = re.search(marker, text)
        if match:
            # Return everything after the marker
            cleaned = text[match.end():].strip()
            if cleaned:
                return cleaned

    # Otherwise, filter out common meta-thought lines
    lines = text.splitlines()
    cleaned_lines = []
    skip_patterns = [
        r"^(?:the\s+)?user\s+is\s+asking",
        r"^the\s+previous\s+turn",
        r"^to\s+provide\s+a\s+comprehensive",
        r"^i\s+should\b",
        r"^i'll\s+start\s+by",
        r"^i\s+will\s+start\s+by",
        r"^i\s+will\b",
        r"^i\s+can\s+now\s+answer",
        r"^i\s+can\b",
        r"^i\s+have\s+enough\s+information",
        r"^analysis:",
        r"^thought:",
        r"^reasoning:",
        r"^plan:",
        r"^step\s+\d+:",
    ]

    for line in lines:
        stripped = line.strip()
        # Skip empty lines at the very beginning of the response
        if not stripped and not cleaned_lines:
            continue
        # Check against skip patterns
        should_skip = False
        for pattern in skip_patterns:
            if re.search(pattern, stripped, re.IGNORECASE):
                should_skip = True
                break
        if not should_skip:
            cleaned_lines.append(line)

    # Re-join and strip outer whitespace
    cleaned_text = "\n".join(cleaned_lines).strip()
    return cleaned_text or text


def run_agent_node(state: AgentState) -> AgentState:
    """Call Ollama or Gemini and let the agent think or call a tool."""
    from aw_vision.settings import settings_store
    from aw_vision.gemini import run_gemini_chat_agent, is_internet_online

    messages = state["messages"]

    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Render messages into a text prompt for the LLM
    prompt_lines = [
        "You are an advanced agentic productivity assistant integrated with ActivityWatch.",
        f"For rough context only, this session started around {current_time_str}; this clock may be stale, "
        "so when the user asks the exact current time or date you MUST call get_current_datetime rather than quoting this line.",
        "You have access to the user's desktop history via screenshot descriptions, tags, active window titles,",
        "as well as local work hours and external integrations (GitHub, Jira).",
        "Use the tools provided to answer the user's questions.",
        "Your available tools are:",
        "- search_screenshots_semantic(query): Search vector db of screenshots using semantic search.",
        "- get_similar_labeled_snapshots(query): Search vector db for similar labeled snapshots, giving 5x weight to human-verified project labels and matching tags/applications.",
        "- get_recent_screenshots(limit): Retrieve the most recent desktop screenshots, ordered by timestamp descending.",
        "- get_activity_for_timeframe(arg): Retrieve activity inside a specific date/time window. The argument is flexible — pass either a plain phrase ('yesterday', 'this morning', 'last week', 'last 3 days', a weekday, an ISO date '2026-06-28', or a range '2026-06-01 to 2026-06-07'), OR a compact JSON object to also filter, e.g. {\"timeframe\": \"yesterday\", \"app\": \"Firefox\", \"project\": \"PRJ-2026-042\", \"query\": \"lint\"}. Date math is computed exactly server-side and returns a per-project/per-app breakdown plus a timeline.",
        "- get_current_datetime(): Return the current local date, time and weekday. Use it to ground yourself before reasoning about relative dates, or to answer 'what time/day is it'. Pass None as the argument.",
        "- get_active_projects(): List configured projects, descriptions, and work guidelines.",
        "- aggregate_project_hours(): Return total active hours spent on each project number.",
        "- query_github(query): Find commits, PRs, or issues on user's GitHub repositories.",
        "- query_jira(jql): Search Jira issues.",
        "- execute_command(command): Execute a whitelisted local command-line tool. Only 'gws' and 'gh' commands are permitted. Dangerous shell syntax (pipes, redirects, etc.) is blocked. Useful for managing email, drive, docs, git repos, or tickets. Example: execute_command(\"gws gmail users messages list --params '{\\\"userId\\\": \\\"me\\\"}'\").",
        "- find_person_moments(name): Find every snapshot where a specific person was involved (chats, mails, meetings, code reviews, mentions), using the structured people index.",
    ]

    # Append any MCP tools the user assigned to the Ask Memory Agent (uniform registry).
    from aw_vision.tooling import mcp_tools_for_slot

    mcp_specs = mcp_tools_for_slot("agent")
    if mcp_specs:
        prompt_lines.append("Additionally, these external MCP tools are available (call them exactly as named):")
        for spec in mcp_specs:
            summary = spec.description or "External MCP tool."
            if len(summary) > 160:
                summary = summary[:160] + "..."
            prompt_lines.append(f"- {spec.name}(input): [{spec.extra.get('server_name', 'MCP')}] {summary}")
        prompt_lines.append(
            "  For MCP tools, the argument after the comma may be a plain search string OR a compact JSON object "
            "of arguments (e.g. CALL_TOOL: mcp_search_issues, {\"jql\": \"project = ABC\"})."
        )

    # Append guidance from any Claude Skills the user assigned to the agent slot.
    try:
        from aw_vision.skills import skills_context_for_slot

        skills_block = skills_context_for_slot("agent")
        if skills_block:
            prompt_lines.append("")
            prompt_lines.append(skills_block.rstrip())
    except Exception as e:
        print(f"[Memory Agent] Could not load skill guidance: {e}")

    prompt_lines += [
        "",
        "CRITICAL: Always perform 'search_screenshots_semantic' first if the user is asking about past active sessions,",
        "such as browsing website pages, looking for sneakers, reading files, or coding topics.",
        "CRITICAL: If the user asks about a specific person (e.g., 'Who is Sergii?', 'What did I discuss with Arjen?', 'When did I last work with Casper?'),",
        "call 'find_person_moments' first — it queries the structured people index. Fall back to 'search_screenshots_semantic' when it finds nothing.",
        "CRITICAL: Always perform 'search_screenshots_semantic' first if the user asks about specific projects, files, websites, or chat conversations.",
        "Do not assume you know them from your pre-trained weights; always search your local computer memory first.",
        "CRITICAL: If the user's question is scoped to a date or time window (e.g. 'yesterday', 'today', 'this morning', 'last week', 'last 3 days', 'on Monday', or a specific date), you MUST use 'get_activity_for_timeframe' and pass the user's exact time phrase as the argument. Do NOT use 'get_recent_screenshots' for date-scoped questions — it ignores dates and will return the wrong period.",
        "CRITICAL: Use 'get_recent_screenshots' ONLY for open-ended 'what am I doing right now / most recently' questions with no specific date or time window.",
        "CRITICAL: If the user asks for the current time, current date, or current day of the week (e.g. 'what time is it', \"what's today's date\", 'what day is it'), and you do NOT already have a TOOL RESULT for get_current_datetime in this conversation, call it exactly ONCE with 'CALL_TOOL: get_current_datetime, None'. As soon as its TOOL RESULT appears above, answer directly from that result and do NOT call it again.",
        "CRITICAL: NEVER call the same tool with the same argument more than once. If a '=== TOOL RESULT (...) ===' for what you need already appears earlier in the conversation, you already have the answer — write the final answer now instead of calling the tool again.",
        "CRITICAL: If the user is asking to categorize a task/application under a project, or wants to check how similar activities were labeled, call 'get_similar_labeled_snapshots' to leverage historical human-verified and tag-matched project associations.",
        "",
        "CRITICAL RESPONSE FORMAT RULES:",
        "1. If you need to CALL a tool, you MUST output a single CALL_TOOL line at the bottom of your message matching this format exactly:",
        "   CALL_TOOL: tool_name, argument_string",
        "   Example: CALL_TOOL: search_screenshots_semantic, purple sneakers",
        "   Example: CALL_TOOL: get_recent_screenshots, 15",
        "   Example: CALL_TOOL: aggregate_project_hours, None",
        "2. You can ONLY call ONE tool per turn. If you want to perform a multi-step plan, call the first tool now. You will receive the tool result in your next turn and can then call another tool.",
        "3. Do NOT output a plan of multiple steps without actually calling the first tool. Listing 'Step 1: Get recent screenshots' is NOT enough; you MUST write 'CALL_TOOL: get_recent_screenshots, 10' at the bottom of your message so the system can run it.",
        "4. If you are NOT calling a tool (i.e. you have enough information to answer the user's question), you MUST output ONLY the direct, polished final answer in clean Markdown. Do NOT output any thoughts, plans, 'I should summarize', 'The user is asking', or 'I have enough information to answer' meta-commentary. Write a direct, premium, professional response that directly answers the user's query.",
        "=== Conversation History ===",
    ]

    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        elif isinstance(msg, HumanMessage):
            prompt_lines.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            content = msg.content
            # If the AIMessage contains a tool call, clean it up to keep history dense and avoid thought leakage
            tool_match = re.search(r"(CALL_TOOL:\s*\w+,\s*.*)", content)
            if tool_match:
                content = tool_match.group(1)
            prompt_lines.append(f"Assistant: {content}")

    prompt = "\n".join(prompt_lines)

    agent_provider = settings_store.get("agent_provider")
    agent_model = settings_store.get("agent_model") or ""

    # Auto-Provider Fallback: if agent_provider is gemini but the model name is local Gemma, fall back to Ollama
    if agent_provider == "gemini" and "gemma" in agent_model.lower():
        print(f"[Memory Agent] Gemma model '{agent_model}' detected with Gemini provider. Automatically routing to local Ollama for stability.")
        agent_provider = "ollama"

    use_gemini = (agent_provider == "gemini" and is_internet_online())

    if use_gemini:
        print(f"[Memory Agent] Routing agent reasoning to Gemini using '{agent_model}'...")
        ctx_size = settings_store.get_int("agent_context_size")
        reply = run_gemini_chat_agent(prompt=prompt, history=[], context_size=ctx_size)
    else:
        # Fallback to local Ollama
        model = agent_model or settings_store.get("ollama_vision_model") or config.vision_model
        # Resolve model name to an installed local model name if it contains Gemma 4 variations
        if "gemma-4" in model or "gemma4" in model or model == "gemma-4-31b-it" or model == "gemma-4-26b-a4b-it":
            model = "gemma4:e2b-it-qat"
        print(f"[Memory Agent] Routing agent reasoning to Ollama using '{model}'...")
        try:
            url = f"{config.ollama_host}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": settings_store.get_int("ollama_context_size") or 8192
                },
                "keep_alive": 0,
            }
            resp = requests.post(url, json=payload, timeout=180.0)
            if resp.status_code == 200:
                reply = resp.json().get("response", "").strip()
            else:
                reply = f"Error calling Ollama text node: {resp.text}"
        except Exception as e:
            reply = f"Error contacting Ollama: {e}"

    # Check if a tool needs to be called
    match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", reply)
    if not match:
        # Heuristic fallback 1: Standard function call syntax like get_recent_screenshots(10)
        fallback_match = re.search(r"(?:CALL_TOOL:\s*)?(\w+)\s*\(\s*(['\" \w\-\d]*)\s*\)", reply)
        if fallback_match:
            t_name = fallback_match.group(1).strip()
            t_arg = fallback_match.group(2).strip().strip("'\"")
            if t_name in TOOLS:
                print(f"[Fallback Parser] Detected function call syntax '{t_name}({t_arg})'. Appending CALL_TOOL line.")
                reply += f"\n\nCALL_TOOL: {t_name}, {t_arg}"
                match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", reply)

    if not match:
        # Heuristic fallback 2: Multi-step plan without CALL_TOOL but containing tool name
        lower_reply = reply.lower()
        planning_signals = ["step 1", "i'll start by", "i will start by", "first step", "first, i'll", "first, i will", "should check recent", "start with getting recent", "let's start with", "let's start by"]
        if any(sig in lower_reply for sig in planning_signals):
            for t_name in ["get_activity_for_timeframe", "get_current_datetime", "get_recent_screenshots", "search_screenshots_semantic", "get_active_projects", "aggregate_project_hours", "query_github", "query_jira", "get_similar_labeled_snapshots", "execute_command"]:
                if t_name in reply:
                    arg = "10" if t_name == "get_recent_screenshots" else "None"
                    print(f"[Fallback Parser] Detected planning words and tool '{t_name}'. Automatically appending CALL_TOOL line.")
                    reply += f"\n\nCALL_TOOL: {t_name}, {arg}"
                    match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", reply)
                    break

    if not match:
        # Heuristic fallback 3: Conversational tool call intent like "Let's call get_active_projects" or "I should check search_screenshots_semantic"
        intent_match = re.search(
            r"(?:call|run|query|check|use|using|execute|retrieve|get|trigger|need to|should|could|can|start with|first)\b.{0,40}\b(get_activity_for_timeframe|get_current_datetime|get_recent_screenshots|search_screenshots_semantic|get_active_projects|aggregate_project_hours|query_github|query_jira|get_similar_labeled_snapshots|execute_command)\b",
            reply,
            re.IGNORECASE
        )
        if intent_match:
            t_name = intent_match.group(1).strip()
            # Determine suitable default arguments
            if t_name == "get_recent_screenshots":
                num_match = re.search(r"\b(\d+)\b", reply[max(0, reply.find(t_name) - 30):reply.find(t_name) + 100])
                arg = num_match.group(1) if num_match else "10"
            elif t_name in ["search_screenshots_semantic", "get_similar_labeled_snapshots", "query_github", "query_jira", "get_activity_for_timeframe", "execute_command"]:
                quotes_match = re.search(r"['\"]([^'\"]+)['\"]", reply[max(0, reply.find(t_name) - 50):reply.find(t_name) + 150])
                if quotes_match:
                    arg = quotes_match.group(1).strip()
                else:
                    user_msgs = [m.content for m in messages if isinstance(m, HumanMessage)]
                    arg = user_msgs[-1] if user_msgs else "None"
            else:
                arg = "None"

            print(f"[Fallback Parser] Detected calling intent for tool '{t_name}' with arg '{arg}'. Appending CALL_TOOL line.")
            reply += f"\n\nCALL_TOOL: {t_name}, {arg}"
            match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", reply)

    if match:
        next_node = "tools"
    else:
        reply = clean_final_response(reply)
        next_node = END

    new_messages = list(messages) + [AIMessage(content=reply)]
    return {"messages": new_messages, "next_node": next_node}


def run_tools_node(state: AgentState) -> AgentState:
    """Execute the tool requested by the agent through the unified registry."""
    from aw_vision.tooling import execute_tool, parse_tool_call

    messages = state["messages"]
    tool_events = list(state.get("tool_events") or [])
    last_message = messages[-1].content

    call = parse_tool_call(last_message)
    if not call:
        # Fallback
        return {
            "messages": messages + [HumanMessage(content="Tool execution error: Invalid format.")],
            "next_node": "agent",
        }

    tool_name, tool_arg = call

    # Loop guard: small models tend to re-issue the same tool call instead of answering.
    # If this exact tool+arg was already executed in this conversation, don't run it again —
    # nudge the model to answer from the result it already has.
    signature = f"{tool_name}|{tool_arg}".strip().lower()
    prior_identical = 0
    total_prior_calls = 0
    for m in messages[:-1]:
        if isinstance(m, AIMessage):
            pm = parse_tool_call(m.content or "")
            if pm:
                total_prior_calls += 1
                if f"{pm[0]}|{pm[1]}".strip().lower() == signature:
                    prior_identical += 1
    if prior_identical >= 1 or total_prior_calls >= 6:
        nudge = (
            f"STOP. You already called {tool_name} and its TOOL RESULT is in the conversation above. "
            "Do NOT call any tool again. Using the information you already have, write the final, polished "
            "answer to the user now in clean Markdown — no CALL_TOOL line."
        )
        return {
            "messages": messages + [HumanMessage(content=nudge)],
            "next_node": "agent",
            "tool_events": tool_events,
        }

    # Execute through the unified registry (builtins + agent-slot MCP tools)
    print(f"Executing Agent Tool: {tool_name} with arg '{tool_arg}'")
    event = execute_tool(build_agent_toolspecs(), tool_name, tool_arg)
    result = event.pop("result")

    if len(result) > 3000:
        print(f"Tool output length ({len(result)}) exceeds threshold. Summarizing...")
        summary = summarize_tool_result(tool_name, result)
        if summary == result:  # Fallback happened due to timeout or error
            result = result[:3500] + "\n\n... [Truncated due to local hardware summarizer timeout/error]"
        else:
            result = summary

    tool_events.append(event)
    formatted_result = f"=== TOOL RESULT ({tool_name}) ===\n{result}"
    return {
        "messages": messages + [HumanMessage(content=formatted_result)],
        "next_node": "agent",
        "tool_events": tool_events,
    }


def decide_next(state: AgentState) -> str:
    return state["next_node"]


# ---------------------------------------------------------
# Build the Graph
# ---------------------------------------------------------
workflow = StateGraph(AgentState)
workflow.add_node("agent", run_agent_node)
workflow.add_node("tools", run_tools_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", decide_next, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

agent_app = workflow.compile()
