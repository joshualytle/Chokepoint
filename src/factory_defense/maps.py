"""Maps — each defines the route packets travel and suggested turret slots.

A map owns its path geometry and the ``pos_at`` math, so the simulation stays
map-agnostic. Switch maps in-game; your loadout places turrets by absolute
position, so different routes need different placements (that's the point).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# game-area width; the info panel sits to the right of this
GW = 720


@dataclass
class GameMap:
    name: str
    path: list[tuple[float, float]]
    slots: list[tuple[float, float]] = field(default_factory=list)  # placement hints
    _segments: list[tuple[float, float, float, float, float, float]] = field(
        default_factory=list, repr=False
    )
    length: float = 0.0

    def __post_init__(self) -> None:
        total = 0.0
        for i in range(len(self.path) - 1):
            ax, ay = self.path[i]
            bx, by = self.path[i + 1]
            seg_len = math.hypot(bx - ax, by - ay)
            self._segments.append((ax, ay, bx, by, seg_len, total))
            total += seg_len
        self.length = total

    def pos_at(self, d: float) -> tuple[float, float]:
        """(x, y) at distance ``d`` along the path."""
        for ax, ay, bx, by, seg_len, acc in self._segments:
            if d <= acc + seg_len:
                t = (d - acc) / seg_len if seg_len else 0.0
                return (ax + (bx - ax) * t, ay + (by - ay) * t)
        return self.path[-1]


MAPS: dict[str, GameMap] = {
    "switchback": GameMap(
        "switchback",
        [(-30, 140), (200, 140), (200, 420), (440, 420),
         (440, 160), (620, 160), (620, 470), (760, 470)],
        slots=[(290, 270), (500, 290), (660, 330)],
    ),
    "spiral": GameMap(
        "spiral",
        [(-30, 320), (560, 320), (560, 120), (160, 120),
         (160, 470), (660, 470), (660, 250), (760, 250)],
        slots=[(330, 320), (360, 200), (520, 470)],
    ),
    "fork": GameMap(
        "fork",
        [(-30, 90), (360, 90), (360, 300), (120, 300),
         (120, 520), (560, 520), (560, 260), (760, 260)],
        slots=[(250, 90), (240, 300), (430, 520)],
    ),
}
MAP_LIST: list[str] = list(MAPS)
