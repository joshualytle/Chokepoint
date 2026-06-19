"""The simulation: alerts flow a topology, queue at nodes, get serviced there.

Pure logic, no pygame — fully testable headless. Rendering reads this state.

The model is a flow network. Packets enter at the source and travel edge to
edge toward the sink. At each node they join a **queue**; a turret attached to
that node drains the queue for the kinds its gun accepts. Two things can go
wrong, and both are real alert-pipeline failure modes:

  * **Loss** — a packet reaches the sink unhandled, or a node's queue overflows
    its capacity. Counts toward ``leaks`` (the drop/MAX_LEAK failure).
  * **Latency** — a packet sits queued past a grace period and starts bleeding
    ``health`` (the SLA/backpressure failure: age-of-oldest-message made real).

So coverage alone isn't enough: a node whose turrets can't keep up with its
inflow backs up, bleeds health, and eventually overflows — per-type backpressure.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arsenal import Turret, compute_synergy_mult, unlocked_at
from .economy import Bank
from .gates import Gate
from .limiter import Limiter
from .maps import Graph
from .metrics import Telemetry
from .packets import DIFFICULTIES, KIND_LIST, WAVES, Packet

PACKET_VOLUME = 12.0
PACKET_SPEED = 60.0

# Failure model.
MAX_LEAK = 12              # dropped/overflowed packets that end the run
START_HEALTH = 100.0       # latency budget; bleeds while packets dwell too long
QUEUE_CAP = 8              # packets a node holds before it overflows (a drop)
DWELL_GRACE = 3.0          # seconds a packet may queue before it bleeds health
DWELL_DRAIN = 3.0          # health/sec drained per packet queued past the grace

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
    """Runs one game on a given topology with a given set of placed turrets."""

    def __init__(
        self,
        game_map: Graph,
        starting_credits: int = STARTING_CREDITS,
        difficulty: str = "easy",
    ):
        self.map = game_map
        self.turrets: list[Turret] = []
        self.gates: list[Gate] = []
        self.limiters: list[Limiter] = []
        self.difficulty = difficulty
        self.starting_credits = starting_credits
        # Created once and kept across resets; the editor holds this same object
        # by reference, so resetting must refill it (in reset) rather than swap it.
        self.bank = Bank(starting_credits)
        self.reset()

    # ---- setup ---- #
    def set_turrets(self, turrets: list[Turret]) -> None:
        """Place turrets and bind each to the node whose queue it serves."""
        self.turrets = turrets
        for i, t in enumerate(turrets):
            t.id = f"T{i + 1}"
            t.cd = 0.0
            t.node = self.map.nearest_node(t.x, t.y)

    def set_gates(self, gates: list[Gate]) -> None:
        """Place gates and bind each to its nearest branching node (a fork)."""
        self.gates = gates
        for i, g in enumerate(gates):
            g.id = f"G{i + 1}"
            node = self.map.nearest_branch_node(g.x, g.y)
            g.node = node if node is not None else ""

    def gate_at(self, node_id: str) -> Gate | None:
        return next((g for g in self.gates if g.node == node_id), None)

    def set_limiters(self, limiters: list[Limiter]) -> None:
        """Place quelimiters and bind each to its nearest node."""
        self.limiters = limiters
        for i, lim in enumerate(limiters):
            lim.id = f"L{i + 1}"
            lim.node = self.map.nearest_node(lim.x, lim.y)
            lim.tokens = 0.0

    def limiter_at(self, node_id: str) -> Limiter | None:
        return next((lim for lim in self.limiters if lim.node == node_id), None)

    def autoroute(self) -> None:
        """Content-based routing: point each gate's kinds at the first branch
        that reaches a turret accepting them. Recompute after turret/gate edits.

        This is the gate "figuring out" where each kind's consumer lives — you
        design the branches, the router sends traffic to the capable one.
        """
        for g in self.gates:
            outs = self.map.branches(g.node)
            routes: dict[str, int] = {}
            for kind in KIND_LIST:
                for i, branch in enumerate(outs):
                    if self._branch_reaches_server(branch, kind):
                        routes[kind] = i
                        break
            g.routes = routes

    def _branch_reaches_server(self, start: str, kind: str) -> bool:
        """Is there a turret accepting ``kind`` anywhere downstream of ``start``?"""
        seen: set[str] = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if self.serves(n, kind):
                return True
            stack.extend(self.map.branches(n))
        return False

    def reset(self) -> None:
        self.packets: list[Packet] = []
        self.wave_idx = 0
        self.leaks = 0
        self.health = START_HEALTH
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
        for lim in self.limiters:
            lim.tokens = 0.0
        self.bank.balance = self.starting_credits  # refill in place; keep the reference
        self.telemetry = Telemetry()  # fresh per run; render reads it for charts/debrief
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

    def queue_at(self, node_id: str) -> list[Packet]:
        """Packets currently queued (not in transit, not dead) at a node, FIFO."""
        return [p for p in self.packets
                if p.moving_to is None and p.at == node_id and not p.dead]

    def serves(self, node_id: str, kind: str) -> bool:
        """Does any turret at this node accept this kind?"""
        return any(t.node == node_id and kind in t.accepts() for t in self.turrets)

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
        self._transit(dt)
        self._process(dt)
        self._route_and_dwell(dt)
        self._release_limiters(dt)
        self._overflow()
        self._drain_health(dt)
        self.packets = [p for p in self.packets if not p.dead]
        for k in KIND_LIST:
            self.stats[k].inflight = sum(1 for p in self.packets if p.kind == k)
        self.telemetry.observe(self, dt)
        self._wave_check()

    def _spawn(self, dt: float) -> None:
        if self.intermission > 0:
            self.intermission -= dt
            return
        self.spawn_clock += dt
        while self.spawn_q and self.spawn_clock >= self.spawn_q[0][0]:
            _, kind = self.spawn_q.pop(0)
            self.packets.append(
                Packet(kind, PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED, at=self.map.source)
            )
            self.stats[kind].spawned += 1
            self.telemetry.on_spawn(kind, self.wave_idx)
            self.started = True

    def _transit(self, dt: float) -> None:
        """Advance in-transit packets; on arrival they join the next node's queue."""
        for p in self.packets:
            if p.dead or p.moving_to is None:
                continue
            p.seg_pos += p.speed * dt
            if p.seg_pos >= self.map.edge_len(p.at, p.moving_to):
                p.at, p.moving_to, p.seg_pos, p.wait = p.moving_to, None, 0.0, 0.0

    def _process(self, dt: float) -> None:
        """Each turret drains the queue at its node for the kinds it accepts."""
        mult = compute_synergy_mult(self.turrets)
        for t in self.turrets:
            t.synergy_mult = mult.get(t.id, 1.0)
            t.cd -= dt
            if t.cd > 0:
                continue
            accepts = t.accepts()
            target = next(
                (p for p in self.queue_at(t.node) if p.kind in accepts and not p.handled),
                None,
            )
            if target is not None:
                t.cd = 1.0 / t.gun.fire_rate
                target.volume -= t.gun.effective_damage() * t.synergy_mult
                if target.volume <= 0:
                    target.handled = True
                    target.dead = True
                    self.stats[target.kind].handled += 1
                    self.telemetry.on_handle(target.kind, t.node, self.wave_idx, target.wait)

    def _dispatch(self, p: Packet) -> None:
        """Send a queued packet onward (gate-routed at a fork); leak it at the sink."""
        outs = self.map.branches(p.at)
        if not outs:                              # unserved at the sink -> a drop
            self._leak(p, "sink")
            return
        if len(outs) == 1:
            idx = 0                               # linear node: only one way on
        else:                                     # fork: a gate routes by kind
            gate = self.gate_at(p.at)
            idx = gate.branch_for(p.kind, len(outs)) if gate is not None else 0
        p.moving_to, p.seg_pos = outs[idx], 0.0

    def _route_and_dwell(self, dt: float) -> None:
        """Queued packets either wait for local service (accruing dwell), sit
        buffered in a limiter (metered out separately, no dwell), or route onward."""
        for p in self.packets:
            if p.dead or p.moving_to is not None:
                continue
            if self.serves(p.at, p.kind):
                p.wait += dt                      # waiting for service -> latency
            elif self.limiter_at(p.at) is not None:
                continue                          # buffered; released by _release_limiters
            else:
                self._dispatch(p)

    def _release_limiters(self, dt: float) -> None:
        """Each limiter releases buffered (unserved) packets onward at its rate."""
        for lim in self.limiters:
            if not lim.node:
                continue
            lim.refill(dt)
            buffered = [p for p in self.queue_at(lim.node) if not self.serves(lim.node, p.kind)]
            i = 0
            while lim.tokens >= 1.0 and i < len(buffered):
                self._dispatch(buffered[i])
                lim.tokens -= 1.0
                i += 1

    def _overflow(self) -> None:
        """A node holding more than its capacity drops the excess (oldest first).

        A quelimiter raises the node's capacity to its buffer size — that's how it
        absorbs a burst without dropping, where a bare node would overflow."""
        for node_id in self.map.nodes:
            lim = self.limiter_at(node_id)
            cap = lim.buffer_cap if lim is not None else QUEUE_CAP
            q = self.queue_at(node_id)
            for p in q[:-cap] if len(q) > cap else []:
                self._leak(p, "overflow")

    def _drain_health(self, dt: float) -> None:
        """Packets queued past the grace period bleed the latency budget."""
        aging = sum(1 for p in self.packets
                    if p.moving_to is None and not p.dead and p.wait > DWELL_GRACE)
        if aging:
            self.health -= DWELL_DRAIN * aging * dt
            if self.health <= 0:
                self.health = 0.0
                self.over, self.won = True, False

    def _leak(self, p: Packet, cause: str) -> None:
        if p.dead:
            return
        p.dead = True
        self.leaks += 1
        self.stats[p.kind].leaked += 1
        self.telemetry.on_leak(p.kind, p.at, self.wave_idx, cause, p.wait)
        if self.leaks >= MAX_LEAK:
            self.over, self.won = True, False

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
