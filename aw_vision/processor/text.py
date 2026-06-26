"""Algorithmic caveman-style text compression used to densify OCR output."""


def caveman_compress_text(text: str) -> str:
    """Algorithmically compress text in a caveman style by stripping filler words and duplicate lines."""
    if not text or text == "N/A":
        return text

    # Split into lines, normalize whitespace, and filter empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Filter common stop words to make each line dense and terse
    filler_words = {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
        "to", "of", "in", "on", "at", "by", "for", "with", "about", "against", "between", "into",
        "through", "during", "before", "after", "above", "below", "from", "up", "down", "in", "out",
        "off", "over", "under", "again", "further", "then", "once"
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
