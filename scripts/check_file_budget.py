#!/usr/bin/env python3
"""Pre-commit ratchet enforcing the AGENTS.md decomposed-file budget.

AGENTS.md caps source files at 300 lines (hard max 400) so modules stay small
enough to load, parse, and reason about inside LLM context windows. This hook
turns that aspiration into a one-way ratchet:

- Files NOT in the baseline fail above ``HARD_LIMIT`` lines.
- Grandfathered files (listed in ``file_budget_baseline.json`` with their line
  count at introduction) may never GROW beyond their recorded count; once one
  shrinks below the hard limit it can be removed from the baseline.

To legitimately restructure a grandfathered file, decompose it instead of
raising its baseline. Raising a baseline number requires explicit human
sign-off in review.
"""

import json
import sys
from pathlib import Path

HARD_LIMIT = 400
BASELINE_PATH = Path(__file__).parent / "file_budget_baseline.json"
SOURCE_SUFFIXES = (".py", ".ts", ".tsx")


def count_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def main(argv: list) -> int:
    try:
        baseline = json.loads(BASELINE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        baseline = {}

    failures = []
    for name in argv:
        path = Path(name)
        if path.suffix not in SOURCE_SUFFIXES or not path.exists():
            continue
        lines = count_lines(path)
        allowed = max(HARD_LIMIT, int(baseline.get(name, 0)))
        if lines > allowed:
            if name in baseline:
                failures.append(
                    f"{name}: {lines} lines exceeds its grandfathered baseline of {baseline[name]} "
                    f"— this file may only shrink. Extract the new code into a focused module instead."
                )
            else:
                failures.append(
                    f"{name}: {lines} lines exceeds the {HARD_LIMIT}-line budget (target 300, AGENTS.md §4). "
                    f"Decompose it into focused modules."
                )

    if failures:
        print("ERROR: file-size budget violations:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
