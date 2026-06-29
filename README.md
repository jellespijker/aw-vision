# aw-vision

Custom ActivityWatch extension for desktop vision tracking, semantic memory search, and automatic project categorization.

## Features
- **KDE Wayland Screenshots**: Background screenshot capture daemon tuned for KDE Wayland.
- **Bulk LLM Processing**: Processes screenshots with local Ollama (`gemma4:e4b-it-qat` model) when CPU & memory usage is low.
- **LanceDB Vector Storage**: Serverless, high-performance scalar & vector database for descriptions and embeddings.
- **LangGraph ReAct Agent**: Converse with your desktop history and query external data sources like Jira, GitHub, and Google Calendar via MCP tools.
- **MCP Integrations**: Connect local (stdio) or remote (Streamable HTTP / SSE) Model Context Protocol servers — e.g. GitHub and Atlassian — with token authentication. Configure them in **Settings → MCP Integrations** and assign each server to individual pipeline prompts and/or the Ask Memory Agent for fine-grained control over where external tools are used. Tokens are AES-256 encrypted at rest.
- **Tight aw-webui Integration**: Adds a "Vision" tab to the default ActivityWatch Web UI.
