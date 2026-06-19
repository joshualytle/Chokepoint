"""A minimal text buffer for the in-app code editor — pure, no pygame.

Holds the source you're editing as a list of lines plus a (row, col) cursor,
with the usual edit operations. render.py feeds it keystrokes and draws it; all
the cursor/insert/delete bookkeeping lives here so it can be unit-tested.
"""

from __future__ import annotations


class TextBuffer:
    def __init__(self, text: str = "") -> None:
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self.lines: list[str] = text.split("\n") or [""]
        self.row = 0
        self.col = 0

    def text(self) -> str:
        return "\n".join(self.lines)

    def _clamp_col(self) -> None:
        self.col = max(0, min(self.col, len(self.lines[self.row])))

    # ---- editing ---- #
    def insert(self, s: str) -> None:
        """Insert printable text (no newlines) at the cursor."""
        line = self.lines[self.row]
        self.lines[self.row] = line[: self.col] + s + line[self.col :]
        self.col += len(s)

    def newline(self) -> None:
        line = self.lines[self.row]
        self.lines[self.row] = line[: self.col]
        self.lines.insert(self.row + 1, line[self.col :])
        self.row += 1
        self.col = 0

    def backspace(self) -> None:
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[: self.col - 1] + line[self.col :]
            self.col -= 1
        elif self.row > 0:  # merge with the previous line
            prev = self.lines[self.row - 1]
            self.col = len(prev)
            self.lines[self.row - 1] = prev + self.lines[self.row]
            del self.lines[self.row]
            self.row -= 1

    def delete(self) -> None:
        """Forward delete (the character to the right of the cursor)."""
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[: self.col] + line[self.col + 1 :]
        elif self.row < len(self.lines) - 1:  # pull up the next line
            self.lines[self.row] = line + self.lines[self.row + 1]
            del self.lines[self.row + 1]

    # ---- movement ---- #
    def left(self) -> None:
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row < len(self.lines) - 1:
            self.row += 1
            self.col = 0

    def up(self) -> None:
        if self.row > 0:
            self.row -= 1
            self._clamp_col()

    def down(self) -> None:
        if self.row < len(self.lines) - 1:
            self.row += 1
            self._clamp_col()

    def home(self) -> None:
        self.col = 0

    def end(self) -> None:
        self.col = len(self.lines[self.row])
