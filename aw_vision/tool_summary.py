"""Tool-result compression for the ReAct agents.

Large tool outputs (screenshot dumps, search results) must be densified before
being fed back as observations: first via a local summarizer model, falling
back to programmatic compression when the model is slow or unavailable.
Extracted from agent.py per the AGENTS.md file-size ratchet.
"""

import requests

from aw_vision.config import config


def caveman_compress_text(text: str) -> str:
    """Algorithmically compress text in a caveman style by stripping filler words and duplicate lines."""
    if not text or text == "N/A":
        return text

    # Split into lines, normalize whitespace, and filter empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Filter common stop words to make each line dense and terse
    filler_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "from",
        "up",
        "down",
        "in",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
    }

    compressed_lines = []
    seen = set()
    for line in lines:
        words = line.split()
        compressed_words = [w for w in words if w.lower() not in filler_words]
        if compressed_words:
            compressed_line = " ".join(compressed_words)
            norm = compressed_line.lower()
            if norm not in seen:
                seen.add(norm)
                compressed_lines.append(compressed_line)

    return " | ".join(compressed_lines)


def programmatic_compress_records(raw_result: str, max_full_records: int = 5) -> str:
    """Programmatically compress a list of formatted records to fit within limits.

    Keeps the first N records in full. For any subsequent records, keeps only the header
    line (containing timestamp, App, and Window) to provide a compact high-level timeline.
    """
    lines = raw_result.splitlines()
    compressed_lines = []
    record_count = 0
    in_sub_fields = False
    has_records = False

    for line in lines:
        stripped = line.strip()
        # Detect records
        is_header = stripped.startswith("- [") or stripped.startswith("--- Result") or stripped.startswith("--- Record")
        if is_header:
            has_records = True
            record_count += 1
            in_sub_fields = record_count > max_full_records
            compressed_lines.append(line)
        elif in_sub_fields:
            # Skip Desc, OCR, Tags lines for records beyond max_full_records
            continue
        else:
            compressed_lines.append(line)

    if not has_records:
        # If it's some other tool output (like GitHub/Jira/project config), just truncate to safe size
        return raw_result[:3000] + "\n\n... [Truncated programmatically to 3000 chars]"

    return "\n".join(compressed_lines)


def summarize_tool_result(tool_name: str, raw_result: str) -> str:
    """Summarize a large tool result into a dense technical overview."""
    if tool_name == "get_recent_screenshots":
        prompt = f"""
You are a highly efficient assistant. Your task is to compress the following list of desktop records into a highly dense chronological timeline of the user's activities.
Keep only unique, key transitions of active applications, window titles, and specific actions.
Omit repetitive consecutive records of the same window unless the description or OCR text changes significantly.
Ensure the output reads as a clear, dense log of what was worked on, so the main agent can directly see the precise timeline of activities.
Format each unique activity strictly as:
- [Time] AppName | WindowTitle: Description summary (OCR keywords)

Raw Desktop Records:
{raw_result[:20000]}
"""
    elif tool_name == "search_screenshots_semantic":
        prompt = f"""
You are a highly efficient assistant. Your task is to compress the following semantic search results into a highly dense summary of matching events.
Highlight the most relevant matches, their apps/window titles, descriptions, and any relevant discussion or text found.
Ensure the main agent gets all the specific, fine-grained details needed to answer the user's query.

Raw Search Results:
{raw_result[:20000]}
"""
    else:
        prompt = f"""
You are a highly efficient text-summarization sub-agent.
Your task is to summarize the following raw tool output from '{tool_name}' into an ultra-dense, structured technical overview.
Identify key findings, activities, files, applications, or discussion points.
Format your response using compact bullet points or semicolons. Omit all polite or introductory filler text.

Raw Tool Output:
{raw_result[:20000]}
"""

    try:
        from aw_vision.settings import settings_store

        url = f"{config.ollama_host}/api/generate"
        payload = {
            "model": config.vision_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": settings_store.get_int("ollama_context_size") or 8192},
            "keep_alive": 0,
        }
        resp = requests.post(url, json=payload, timeout=25.0)
        if resp.status_code == 200:
            summary = resp.json().get("response", "").strip()
            if len(summary) >= 50:
                return f"[Compressed representation of {tool_name} results]\n{summary}"
            else:
                print(
                    f"Ollama returned empty or too-short response ({len(summary)} chars). Falling back to programmatic compression."
                )
        else:
            print(f"Ollama returned status {resp.status_code}. Falling back to programmatic compression.")
    except Exception as e:
        print(f"Error/timeout in tool result summarizer: {e}. Falling back to programmatic compression.")

    # Programmatic compression fallback
    compressed = programmatic_compress_records(raw_result, max_full_records=4)
    return f"[Programmatically compressed to fit context limit]\n{compressed}"
