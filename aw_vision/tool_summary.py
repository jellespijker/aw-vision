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


def programmatic_compress_records(raw_result: str, max_full_records: int = 5, max_total_records: int = 15) -> str:
    """Programmatically compress a list of formatted records to fit within limits.

    Keeps the first N records in full. For any subsequent records, keeps only the header
    line (containing timestamp, App, and Window) to provide a compact high-level timeline.
    Caps the total number of records at max_total_records to avoid context bloating.
    """
    lines = raw_result.splitlines()
    compressed_lines = []
    record_count = 0
    in_sub_fields = False
    has_records = False
    skipped_count = 0

    for line in lines:
        stripped = line.strip()
        # Detect records
        is_header = stripped.startswith("- [") or stripped.startswith("--- Result") or stripped.startswith("--- Record")
        if is_header:
            has_records = True
            record_count += 1
            if record_count > max_total_records:
                skipped_count += 1
                continue
            in_sub_fields = record_count > max_full_records
            compressed_lines.append(line)
        elif in_sub_fields:
            # Skip Desc, OCR, Tags lines for records beyond max_full_records
            continue
        else:
            if record_count > max_total_records:
                continue
            compressed_lines.append(line)

    if skipped_count > 0:
        compressed_lines.append(f"\n  ... [{skipped_count} more chronological records omitted to fit context limit; query a narrower timeframe for full detail]")

    if not has_records:
        # If it's some other tool output (like GitHub/Jira/project config), just truncate to safe size
        return raw_result[:3000] + "\n\n... [Truncated programmatically to 3000 chars]"

    return "\n".join(compressed_lines)


def divide_and_conquer_compress(tool_name: str, raw_result: str, depth: int = 0) -> str:
    """Compress raw_result using a divide-and-conquer strategy when it exceeds limits."""
    from aw_vision.settings import settings_store

    max_chunk = settings_store.get_int("max_summarize_chunk_chars") or 15000
    if len(raw_result) <= max_chunk or depth >= 2:
        return raw_result

    print(f"Compressing {tool_name} output using divide-and-conquer (size: {len(raw_result)} chars, depth: {depth})...")

    # Split into lines
    lines = raw_result.splitlines()
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # count newline
        if current_len + line_len > max_chunk and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    # If we only have 1 chunk, we can't divide it further without line splitting,
    # so just return raw_result up to safe limit
    if len(chunks) <= 1:
        return raw_result[:max_chunk]

    # Summarize each chunk
    summarized_chunks = []
    for idx, chunk in enumerate(chunks):
        print(f"  Summarizing chunk {idx + 1}/{len(chunks)} of size {len(chunk)}...")
        chunk_summary = _summarize_chunk(tool_name, chunk)
        summarized_chunks.append(chunk_summary)

    combined = "\n".join(summarized_chunks)

    # If the combined summary is still too large, compress it recursively
    if len(combined) > max_chunk:
        return divide_and_conquer_compress(tool_name, combined, depth + 1)

    return combined


def _summarize_chunk(tool_name: str, chunk_content: str) -> str:
    """Summarize a single chunk of tool result using local Ollama model, falling back to programmatic."""
    prompt = f"""
You are a highly efficient text-compression sub-agent.
Your task is to summarize the following chunk of raw tool output from '{tool_name}' into a highly dense, structured summary.
Keep all unique actions, App names, files, timestamps, and findings.
Do not omit key transitions or critical information.
Format your response using compact bullet points. Omit all polite or introductory filler text.

Raw Chunk Content:
{chunk_content}
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
            if len(summary) >= 30:
                return summary
            else:
                print(f"Ollama returned too-short chunk response ({len(summary)} chars). Falling back to programmatic compression.")
        else:
            print(f"Ollama returned chunk status {resp.status_code}. Falling back to programmatic compression.")
    except Exception as e:
        print(f"Error/timeout in chunk summarizer: {e}. Falling back to programmatic compression.")

    # Programmatic compression fallback for this single chunk
    return programmatic_compress_records(chunk_content, max_full_records=3, max_total_records=10)


def summarize_tool_result(tool_name: str, raw_result: str) -> str:
    """Summarize a large tool result into a dense technical overview."""
    compressed_raw = divide_and_conquer_compress(tool_name, raw_result)

    if tool_name == "get_recent_screenshots":
        prompt = f"""
You are a highly efficient assistant. Your task is to compress the following list of desktop records into a highly dense chronological timeline of the user's activities.
Keep only unique, key transitions of active applications, window titles, and specific actions.
Omit repetitive consecutive records of the same window unless the description or OCR text changes significantly.
Ensure the output reads as a clear, dense log of what was worked on, so the main agent can directly see the precise timeline of activities.
Format each unique activity strictly as:
- [Time] AppName | WindowTitle: Description summary (OCR keywords)

Raw Desktop Records:
{compressed_raw}
"""
    elif tool_name == "get_activity_for_timeframe":
        prompt = f"""
You are a highly efficient assistant. Your task is to compress the following chronological activity timeline into a highly dense chronological log.
Keep each unique activity with a short description of what was being done.
Omit repetitive consecutive lines if they represent the exact same task with no progress or change, but keep unique transitions.
Ensure the output reads as a clear, dense timeline of actions, so the main agent can see exactly what was worked on.
Format each unique activity strictly as:
- [TimeRanges] AppName | Short Description (ProjectKey)

Raw Activity Timeline:
{compressed_raw}
"""
    elif tool_name == "search_screenshots_semantic":
        prompt = f"""
You are a highly efficient assistant. Your task is to compress the following semantic search results into a highly dense summary of matching events.
Highlight the most relevant matches, their apps/window titles, descriptions, and any relevant discussion or text found.
Ensure the main agent gets all the specific, fine-grained details needed to answer the user's query.

Raw Search Results:
{compressed_raw}
"""
    else:
        prompt = f"""
You are a highly efficient text-summarization sub-agent.
Your task is to summarize the following raw tool output from '{tool_name}' into an ultra-dense, structured technical overview.
Identify key findings, activities, files, applications, or discussion points.
Format your response using compact bullet points or semicolons. Omit all polite or introductory filler text.

Raw Tool Output:
{compressed_raw}
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
    if tool_name == "get_activity_for_timeframe":
        compressed = programmatic_compress_records(raw_result, max_full_records=30, max_total_records=50)
    else:
        compressed = programmatic_compress_records(raw_result, max_full_records=4)
    return f"[Programmatically compressed to fit context limit]\n{compressed}"
