"""High-score persistence — a tiny stdlib helper, never raises.

Reads/writes a single integer to a file so a best score survives between runs.
Isolated here so it stays testable and the game loop can call it without fear.
"""

from __future__ import annotations


def load_highscore(path: str) -> int:
    """Best score on record, or 0 if the file is missing/unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_highscore(path: str, score: int) -> int:
    """Persist ``score`` if it beats the record; return the resulting best."""
    best = max(load_highscore(path), score)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(best))
    except OSError:
        pass  # never raise into the game loop
    return best
