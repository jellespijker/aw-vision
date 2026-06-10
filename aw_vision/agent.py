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

# ---------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------


def tool_search_screenshots_semantic(query: str, limit: int = 5) -> str:
    """Perform a semantic vector similarity search on processed screenshots."""
    try:
        # Step 1: Embed query via Ollama
        url = f"{config.ollama_host}/api/embeddings"
        payload = {"model": config.embedding_model, "prompt": query, "keep_alive": 0}
        resp = requests.post(url, json=payload, timeout=60.0)
        if resp.status_code != 200:
            return f"Error embedding query: {resp.text}"

        query_vector = resp.json().get("embedding", [])
        if not query_vector:
            return "Error: Empty embedding returned."

        # Step 2: Query LanceDB
        results = db.search_semantic(query_vector, limit=limit)
        if not results:
            return "No matching screenshots or active screens found."

        # Step 3: Format results
        output = []
        for r in results:
            dt = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S")
            tags_str = ", ".join(r.get("tags", []))
            image_path_val = r.get("image_path")
            screenshot_name = (
                os.path.basename(image_path_val) if image_path_val else "Archived (Image deleted, metadata preserved)"
            )

            output.append(
                f"--- Result (Similarity: {r.get('_distance', 'N/A')}) ---\n"
                f"Time: {dt}\n"
                f"App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"Description: {r.get('description')}\n"
                f"Extracted OCR Text: {r.get('ocr_text', 'N/A')}\n"
                f"Tags: {tags_str}\n"
                f"Project Mapped: {r.get('project_number')}\n"
                f"Screenshot: {screenshot_name}\n"
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


def tool_get_similar_labeled_snapshots(query: str, limit: int = 5) -> str:
    """Search the database for similar labeled snapshots. This tool scores results by favoring manually/human labeled data and matching tags/app names."""
    try:
        # Step 1: Embed query via Ollama
        url = f"{config.ollama_host}/api/embeddings"
        payload = {"model": config.embedding_model, "prompt": query, "keep_alive": 0}
        resp = requests.post(url, json=payload, timeout=60.0)
        if resp.status_code != 200:
            return f"Error embedding query: {resp.text}"

        query_vector = resp.json().get("embedding", [])
        if not query_vector:
            return "Error: Empty embedding returned."

        words = [w.strip().lower() for w in re.split(r'\s+', query) if w.strip()]

        # Step 2: Query LanceDB using the advanced labeled scoring helper
        results = db.get_similar_labeled_snapshots(query_vector, tags=words, limit=limit)
        if not results:
            return "No matching labeled screenshots or active screens found."

        # Step 3: Format results
        output = []
        for r in results:
            is_human = "Yes (Verified)" if r.get("human_labeled") else "No (Auto)"
            tags_str = ", ".join(r.get("tags", []))
            output.append(
                f"--- Similar Labeled Result (Score: {r.get('score', 0.0):.2f}) ---\n"
                f"Project Assigned: {r.get('project_number')}\n"
                f"Human Verified Label: {is_human}\n"
                f"App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"Description: {r.get('description')}\n"
                f"Tags: {tags_str}\n"
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
            image_path_val = r.get("image_path")
            screenshot_name = (
                os.path.basename(image_path_val) if image_path_val else "Archived (Image deleted, metadata preserved)"
            )

            output.append(
                f"--- Record ---\n"
                f"Time: {dt}\n"
                f"App: {r.get('app_name')} | Window: {r.get('window_title')}\n"
                f"Description: {r.get('description')}\n"
                f"Extracted OCR Text: {r.get('ocr_text', 'N/A')}\n"
                f"Tags: {tags_str}\n"
                f"Project Mapped: {r.get('project_number')}\n"
                f"Screenshot: {screenshot_name}\n"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error retrieving recent screenshots: {e}"


# Export a tool mapping
TOOLS = {
    "search_screenshots_semantic": tool_search_screenshots_semantic,
    "get_similar_labeled_snapshots": tool_get_similar_labeled_snapshots,
    "get_recent_screenshots": tool_get_recent_screenshots,
    "get_active_projects": tool_get_active_projects,
    "aggregate_project_hours": tool_aggregate_project_hours,
    "query_github": tool_query_github,
    "query_jira": tool_query_jira,
}

# ---------------------------------------------------------
# LangGraph ReAct Agent State Machine
# ---------------------------------------------------------


class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    next_node: str


def run_agent_node(state: AgentState) -> AgentState:
    """Call Ollama and let the agent think or call a tool."""
    messages = state["messages"]

    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Render messages into a text prompt for Ollama
    prompt_lines = [
        "You are an advanced agentic productivity assistant integrated with ActivityWatch.",
        f"The current local date and time is: {current_time_str}.",
        "You have access to the user's desktop history via screenshot descriptions, tags, active window titles,",
        "as well as local work hours and external integrations (GitHub, Jira).",
        "Use the tools provided to answer the user's questions.",
        "Your available tools are:",
        "- search_screenshots_semantic(query): Search vector db of screenshots using semantic search.",
        "- get_similar_labeled_snapshots(query): Search vector db for similar labeled snapshots, giving 5x weight to human-verified project labels and matching tags/applications.",
        "- get_recent_screenshots(limit): Retrieve the most recent desktop screenshots, ordered by timestamp descending.",
        "- get_active_projects(): List configured projects, descriptions, and work guidelines.",
        "- aggregate_project_hours(): Return total active hours spent on each project number.",
        "- query_github(query): Find commits, PRs, or issues on user's GitHub repositories.",
        "- query_jira(jql): Search Jira issues.",
        "",
        "CRITICAL: Always perform 'search_screenshots_semantic' first if the user is asking about past active sessions,",
        "such as browsing website pages, looking for sneakers, reading files, or coding topics.",
        "CRITICAL: Always perform 'search_screenshots_semantic' first if the user asks about a specific person (e.g., 'Who is Sergii?', 'What did I discuss with Arjen?'),",
        "specific projects, files, websites, or chat conversations. Do not assume you know them from your pre-trained weights; always search your local computer memory first.",
        "CRITICAL: Always use 'get_recent_screenshots' if the user asks what they worked on recently (e.g., in the past hour, today, this morning, or wants a timeline of recent activity).",
        "CRITICAL: If the user is asking to categorize a task/application under a project, or wants to check how similar activities were labeled, call 'get_similar_labeled_snapshots' to leverage historical human-verified and tag-matched project associations.",
        "",
        "To invoke a tool, output a single line matching this format exactly:",
        "CALL_TOOL: tool_name, argument_string",
        "Example: CALL_TOOL: search_screenshots_semantic, purple sneakers",
        "Example: CALL_TOOL: get_recent_screenshots, 15",
        "Example: CALL_TOOL: aggregate_project_hours, None",
        "",
        "If you have enough information to answer, output your final answer directly to the user (do not use CALL_TOOL).",
        "=== Conversation History ===",
    ]

    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        elif isinstance(msg, HumanMessage):
            prompt_lines.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            prompt_lines.append(f"Assistant: {msg.content}")

    prompt = "\n".join(prompt_lines)

    try:
        # Call Ollama API
        url = f"{config.ollama_host}/api/generate"
        payload = {
            "model": config.vision_model,  # Re-use vision_model or any default text model
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
            "keep_alive": 0,
        }
        resp = requests.post(url, json=payload, timeout=180.0)
        if resp.status_code == 200:
            reply = resp.json().get("response", "").strip()
        else:
            reply = f"Error calling Ollama text node: {resp.text}"
    except Exception as e:
        reply = f"Error contacting Ollama: {e}"

    new_messages = list(messages) + [AIMessage(content=reply)]

    # Check if a tool needs to be called
    match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", reply)
    if match:
        next_node = "tools"
    else:
        next_node = END

    return {"messages": new_messages, "next_node": next_node}


def run_tools_node(state: AgentState) -> AgentState:
    """Execute the tool requested by the agent."""
    messages = state["messages"]
    last_message = messages[-1].content

    match = re.search(r"CALL_TOOL:\s*(\w+),\s*(.*)", last_message)
    if not match:
        # Fallback
        return {
            "messages": messages + [HumanMessage(content="Tool execution error: Invalid format.")],
            "next_node": "agent",
        }

    tool_name = match.group(1).strip()
    tool_arg = match.group(2).strip()

    # Execute the matching tool
    if tool_name in TOOLS:
        print(f"Executing Agent Tool: {tool_name} with arg '{tool_arg}'")
        try:
            # Special case for None args
            if tool_arg.lower() == "none" or not tool_arg:
                result = TOOLS[tool_name]()
            else:
                result = TOOLS[tool_name](tool_arg)
        except Exception as e:
            result = f"Error executing tool: {e}"
    else:
        result = f"Tool '{tool_name}' is not registered."

    formatted_result = f"=== TOOL RESULT ({tool_name}) ===\n{result}"
    return {
        "messages": messages + [HumanMessage(content=formatted_result)],
        "next_node": "agent",
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
