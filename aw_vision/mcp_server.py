"""aw-vision as an MCP server: your visual memory as infrastructure.

Exposes the READ-tier memory tools over stdio so external agents (Claude
Code, IDE assistants, other MCP clients) can query the screenshot memory:

    claude mcp add aw-vision -- poetry run aw-vision-mcp

Only read tools are exposed deliberately — no relabeling, no command
execution — so an external agent can never mutate the database or reach the
whitelisted CLI runner. Runs standalone against LanceDB; it never starts the
watcher/processor daemons.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aw-vision")


@mcp.tool()
def search_screenshots_semantic(query: str, limit: int = 5) -> str:
    """Semantic search over the user's desktop screenshot memory (descriptions, OCR text, tags)."""
    from aw_vision.agent import tool_search_screenshots_semantic

    return tool_search_screenshots_semantic(query, limit=limit)


@mcp.tool()
def find_person_moments(name: str) -> str:
    """Find every captured moment involving a specific person (chats, mails, meetings, mentions)."""
    from aw_vision.agent import tool_find_person_moments

    return tool_find_person_moments(name)


@mcp.tool()
def get_activity_for_timeframe(timeframe: str) -> str:
    """Desktop activity for a time window ('yesterday', 'last week', an ISO date or range), with per-project/app hour breakdowns and a timeline."""
    from aw_vision.agent import tool_get_activity_for_timeframe

    return tool_get_activity_for_timeframe(timeframe)


@mcp.tool()
def get_recent_screenshots(limit: int = 10) -> str:
    """The most recent processed desktop snapshots, newest first."""
    from aw_vision.agent import tool_get_recent_screenshots

    return tool_get_recent_screenshots(str(limit))


@mcp.tool()
def get_active_projects() -> str:
    """The configured work projects with their descriptions and classification guidelines."""
    from aw_vision.agent import tool_get_active_projects

    return tool_get_active_projects()


@mcp.tool()
def aggregate_project_hours() -> str:
    """Total active hours recorded per project across the whole memory."""
    from aw_vision.agent import tool_aggregate_project_hours

    return tool_aggregate_project_hours()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
