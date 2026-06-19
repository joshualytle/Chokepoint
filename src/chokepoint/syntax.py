"""Tiny single-line Python tokenizer for the in-app code editor's highlighting.

``spans(line)`` splits one line into (text, kind) pieces in order, where kind is
"kw" (keyword), "num", "comment", or "text". It's deliberately line-local and
simple — no multi-line string tracking — which is plenty for colorizing a short
loadout.py and keeps it pure and testable.
"""

from __future__ import annotations

import keyword
import re

_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*|\s+|[^\w\s]+")
_KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}


def spans(line: str) -> list[tuple[str, str]]:
    """Tokenize one line into ordered (text, kind) spans for the editor."""
    code, sep, comment = line.partition("#")
    out: list[tuple[str, str]] = []
    for m in _TOKEN.finditer(code):
        tok = m.group()
        if not tok.strip():
            kind = "text"
        elif tok in _KEYWORDS:
            kind = "kw"
        elif tok[0].isdigit():
            kind = "num"
        else:
            kind = "text"
        out.append((tok, kind))
    if sep:  # everything from the first '#' is a comment
        out.append(("#" + comment, "comment"))
    return out
