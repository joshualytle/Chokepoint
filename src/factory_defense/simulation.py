"""The simulation: packets flood a map, turrets process the kinds they accept.

Pure logic, no pygame — fully testable headless. Rendering reads this state.

Key teaching metric: per-kind ``leaked`` and the ``coverage_gaps`` set. If no
placed turret accepts a kind, every packet of that kind leaks — the alert-
pipeline lesson that typed consumers must collectively cover the event mix, with
enough throughput per type to survive bursts.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arsenal import Turret, compute_synergy_mult, unlocked_at
from .economy import Bank
from .maps import GameMap
from .packets import DIFFICULTIES, KIND_LIST, WAVES, Packet

PACKET_VOLUME = 12.0
PACKET_SPEED = 60.0
MAX_LEAK = 12

# Economy: starting budget, and income granted each time a wave is cleared.
# Income scales with the wave number so spending power grows as threats escalate.
STARTING_CREDITS = 250
WAVE_INCOME_BASE = 100
WAVE_INCOME_STEP = 25


@dataclass
class KindStat:
    spawned: int = 0
    handled: int = 0
    leaked: int = 0
    inflight: int = 0


class World:
    """Runs one game on a given map with a given set of placed turrets."""

    def __init__(
        self,
        game_map: GameMap,
        starting_credits: int = STARTING_CREDITS,
        difficulty: str = "easy",
    ):
        self.map = game_map
        self.turrets: list[Turret] = []
        self.difficulty = difficulty
        self.starting_credits = starting_credits
        # Created once and kept across resets; the editor holds this same object
        # by reference, so resetting must refill it (in reset) rather than swap it.
        self.bank = Bank(starting_credits)
        self.reset()

    # ---- setup ---- #
    def set_turrets(self, turrets: list[Turret]) -> None:
        self.turrets = turrets
        for i, t in enumerate(turrets):
            t.id = f"T{i + 1}"
            t.cd = 0.0

    def reset(self) -> None:
        self.packets: list[Packet] = []
        self.wave_idx = 0
        self.leaks = 0
        self.spawn_q: list[tuple[float, str]] = []
        self.spawn_clock = 0.0
        self.intermission = 0.0
        self.started = False
        self.paused = False
        self.over = False
        self.won = False
        self.stats: dict[str, KindStat] = {k: KindStat() for k in KIND_LIST}
        for t in self.turrets:
            t.cd = 0.0
        self.bank.balance = self.starting_credits  # refill in place; keep the reference
        self.load_wave(0)

    @property
    def level(self) -> int:
        return self.wave_idx + 1

    def unlocked(self) -> set[str]:
        return unlocked_at(self.wave_idx)

    def coverage(self) -> frozenset[str]:
        cov: frozenset[str] = frozenset()
        for t in self.turrets:
            cov |= t.accepts()
        return cov

    def coverage_gaps(self) -> set[str]:
        """Kinds that have appeared but no turret can process."""
        seen = {k for k, s in self.stats.items() if s.spawned > 0}
        return seen - set(self.coverage())

    def load_wave(self, i: int) -> None:
        # The active difficulty strategy decides the next wave's groups, reading
        # how much of each kind has leaked so far (used by the adaptive profile).
        leaked = {k: s.leaked for k, s in self.stats.items()}
        strategy = DIFFICULTIES.get(self.difficulty, DIFFICULTIES["easy"])
        groups = strategy(i, leaked)
        q: list[tuple[float, str]] = []
        for kind, count, gap, delay in groups:
            for k in range(count):
                q.append((delay + k * gap, kind))
        q.sort()
        self.spawn_q = q
        self.spawn_clock = 0.0

    # ---- main step ---- #
    def step(self, dt: float) -> None:
        if self.over or self.paused:
            return
        self._spawn(dt)
        self._move(dt)
        self._process(dt)
        self.packets = [p for p in self.packets if not p.dead]
        for k in KIND_LIST:
            self.stats[k].inflight = sum(1 for p in self.packets if p.kind == k)
        self._wave_check()

    def _spawn(self, dt: float) -> None:
        if self.intermission > 0:
            self.intermission -= dt
            return
        self.spawn_clock += dt
        while self.spawn_q and self.spawn_clock >= self.spawn_q[0][0]:
            _, kind = self.spawn_q.pop(0)
            self.packets.append(
                Packet(kind, PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED)
            )
            self.stats[kind].spawned += 1
            self.started = True

    def _move(self, dt: float) -> None:
        for p in self.packets:
            p.d += p.speed * dt
            if p.d >= self.map.length:
                p.dead = True
                if not p.handled:
                    self.leaks += 1
                    self.stats[p.kind].leaked += 1
                    if self.leaks >= MAX_LEAK:
                        self.over, self.won = True, False

    def _process(self, dt: float) -> None:
        mult = compute_synergy_mult(self.turrets)
        for t in self.turrets:
            t.synergy_mult = mult.get(t.id, 1.0)
            t.cd -= dt
            accepts = t.accepts()
            rng = t.range()
            # candidates: accepted, alive, in range — target the furthest along
            target = None
            best_d = -1.0
            for p in self.packets:
                if p.dead or p.handled or p.kind not in accepts:
                    continue
                px, py = self.map.pos_at(p.d)
                if (px - t.x) ** 2 + (py - t.y) ** 2 <= rng * rng and p.d > best_d:
                    target, best_d = p, p.d
            if target is not None and t.cd <= 0:
                t.cd = 1.0 / t.gun.fire_rate
                target.volume -= t.gun.effective_damage() * t.synergy_mult
                if target.volume <= 0:
                    target.handled = True
                    target.dead = True
                    self.stats[target.kind].handled += 1

    def wave_income(self, level: int) -> int:
        """Credits granted for clearing the wave at ``level`` (scales upward)."""
        return WAVE_INCOME_BASE + WAVE_INCOME_STEP * level

    def _wave_check(self) -> None:
        if (self.started and not self.over and not self.spawn_q
                and self.intermission <= 0 and not self.packets):
            self.wave_idx += 1
            self.bank.earn(self.wave_income(self.wave_idx))  # reward for the cleared wave
            if self.wave_idx >= len(WAVES) and self.wave_idx >= 12:
                self.over, self.won = True, True
            else:
                self.load_wave(self.wave_idx)
                self.intermission = 2.5
                self.started = False
