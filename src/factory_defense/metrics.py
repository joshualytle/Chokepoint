"""Telemetry — the observability backend for a run.

The simulation *moves* alerts; this module *measures* the movement. The World
feeds it events (a packet spawned, handled, or lost) and samples gauges over
time; everything you'd want to visualize or post-mortem is aggregated here. It's
pure (no pygame, no network), so it's fully unit-testable and the renderer just
reads it.

The five facts we collect (the "invented data"), each modeled on what a real
alert pipeline emits:

  * KindFlow  (kind x wave): spawned/handled/leaked/peak_inflight — throughput
    and loss by type over time. Like per-source success/error counts.
  * NodeLoad  (node x wave): peak_queue, overflow_drops, dwell, load_fraction —
    bottleneck detection. Like SQS queue depth / Lambda throttles.
  * Latency   (per kind): a dwell-time Histogram -> p50/p95/max. Like
    age-of-oldest-message / Duration percentiles.
  * Trend     (sampled ~1/s): health, inflight, queue, credits over the run.
  * Efficiency(live): deployed turret cost per handled packet — the
    over-provisioning KPI ("better systems, not more turrets").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .arsenal import gun_cost

SAMPLE_INTERVAL = 1.0   # seconds of sim time between trend samples
TREND_CAP = 600         # keep at most this many trend points (a rolling window)


@dataclass
class Histogram:
    """Fixed-bucket histogram — bounded memory, percentiles from bucket edges.

    This is how real metrics systems summarize latency: you don't keep every
    sample, you keep counts per bucket and read percentiles off the edges.
    """

    bounds: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)
    counts: list[int] = field(default_factory=list)
    total: int = 0
    sum: float = 0.0
    hi: float = 0.0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * (len(self.bounds) + 1)  # one extra bin for > last bound

    def add(self, value: float) -> None:
        self.total += 1
        self.sum += value
        self.hi = max(self.hi, value)
        for i, edge in enumerate(self.bounds):
            if value <= edge:
                self.counts[i] += 1
                return
        self.counts[-1] += 1

    def percentile(self, p: float) -> float:
        """Approximate the p-th percentile from bucket boundaries (0 if empty)."""
        if self.total == 0:
            return 0.0
        target = p / 100.0 * self.total
        edges = (*self.bounds, self.hi or self.bounds[-1])
        cum = 0
        for i, c in enumerate(self.counts):
            cum += c
            if cum >= target:
                return edges[i]
        return self.hi

    @property
    def mean(self) -> float:
        return self.sum / self.total if self.total else 0.0


@dataclass
class KindWave:
    spawned: int = 0
    handled: int = 0
    leaked: int = 0
    peak_inflight: int = 0


@dataclass
class NodeWave:
    peak_queue: int = 0
    overflow_drops: int = 0
    dwell_seconds: float = 0.0
    load_ticks: int = 0     # observe-ticks where the node held >=1 packet
    total_ticks: int = 0

    @property
    def load_fraction(self) -> float:
        return self.load_ticks / self.total_ticks if self.total_ticks else 0.0


@dataclass
class TrendPoint:
    t: float
    wave: int
    health: float
    inflight: int
    queue: int
    credits: int


class Telemetry:
    """Aggregates a single run's metrics. Reset per run."""

    def __init__(self) -> None:
        self.kind_wave: dict[tuple[str, int], KindWave] = {}
        self.node_wave: dict[tuple[str, int], NodeWave] = {}
        self.latency: dict[str, Histogram] = {}
        self.trend: list[TrendPoint] = []
        self._elapsed = 0.0
        self._sample_clock = 0.0

    # ---- get-or-create helpers ---- #
    def _kw(self, kind: str, wave: int) -> KindWave:
        return self.kind_wave.setdefault((kind, wave), KindWave())

    def _nw(self, node: str, wave: int) -> NodeWave:
        return self.node_wave.setdefault((node, wave), NodeWave())

    def _lat(self, kind: str) -> Histogram:
        return self.latency.setdefault(kind, Histogram())

    # ---- discrete events from the simulation ---- #
    def on_spawn(self, kind: str, wave: int) -> None:
        self._kw(kind, wave).spawned += 1

    def on_handle(self, kind: str, node: str, wave: int, dwell: float) -> None:
        self._kw(kind, wave).handled += 1
        self._nw(node, wave).dwell_seconds += dwell
        self._lat(kind).add(dwell)

    def on_leak(self, kind: str, node: str, wave: int, cause: str, dwell: float) -> None:
        self._kw(kind, wave).leaked += 1
        if cause == "overflow":
            self._nw(node, wave).overflow_drops += 1
            self._lat(kind).add(dwell)

    # ---- periodic gauge sampling ---- #
    def observe(self, world: object, dt: float) -> None:
        """Called each step: update per-wave peaks and sample trend ~1/s.

        Typed loosely (``world: object``) to avoid importing World here and
        creating an import cycle; we only read attributes the World exposes.
        """
        w = world.wave_idx                      # type: ignore[attr-defined]
        for kind, stat in world.stats.items():  # type: ignore[attr-defined]
            kw = self._kw(kind, w)
            kw.peak_inflight = max(kw.peak_inflight, stat.inflight)
        total_queue = 0
        for node_id in world.map.nodes:          # type: ignore[attr-defined]
            depth = len(world.queue_at(node_id))  # type: ignore[attr-defined]
            total_queue += depth
            nw = self._nw(node_id, w)
            nw.peak_queue = max(nw.peak_queue, depth)
            nw.total_ticks += 1
            if depth > 0:
                nw.load_ticks += 1

        self._elapsed += dt
        self._sample_clock += dt
        if self._sample_clock >= SAMPLE_INTERVAL:
            self._sample_clock = 0.0
            inflight = sum(s.inflight for s in world.stats.values())  # type: ignore[attr-defined]
            self.trend.append(TrendPoint(
                t=round(self._elapsed, 1), wave=w,
                health=world.health, inflight=inflight,    # type: ignore[attr-defined]
                queue=total_queue, credits=world.bank.balance,  # type: ignore[attr-defined]
            ))
            if len(self.trend) > TREND_CAP:
                self.trend = self.trend[-TREND_CAP:]

    # ---- aggregate queries (sum across waves) ---- #
    def kind_summary(self) -> dict[str, KindWave]:
        out: dict[str, KindWave] = {}
        for (kind, _wave), kw in self.kind_wave.items():
            acc = out.setdefault(kind, KindWave())
            acc.spawned += kw.spawned
            acc.handled += kw.handled
            acc.leaked += kw.leaked
            acc.peak_inflight = max(acc.peak_inflight, kw.peak_inflight)
        return out

    def node_summary(self) -> dict[str, NodeWave]:
        out: dict[str, NodeWave] = {}
        for (node, _wave), nw in self.node_wave.items():
            acc = out.setdefault(node, NodeWave())
            acc.peak_queue = max(acc.peak_queue, nw.peak_queue)
            acc.overflow_drops += nw.overflow_drops
            acc.dwell_seconds += nw.dwell_seconds
            acc.load_ticks += nw.load_ticks
            acc.total_ticks += nw.total_ticks
        return out

    def efficiency(self, world: object) -> dict[str, float]:
        """Live over-provisioning KPI: standing fleet cost per handled packet."""
        turrets = world.turrets               # type: ignore[attr-defined]
        deployed_cost = sum(gun_cost(t.gun) for t in turrets)
        handled = sum(s.handled for s in world.stats.values())  # type: ignore[attr-defined]
        return {
            "deployed_cost": float(deployed_cost),
            "handled": float(handled),
            "cost_per_handled": deployed_cost / handled if handled else 0.0,
        }


# --------------------------------------------------------------------------- #
#  Failure debrief — an incident post-mortem built from the telemetry
# --------------------------------------------------------------------------- #

@dataclass
class Debrief:
    cause: str
    lines: list[str]


def summarize_failure(world: object) -> Debrief:
    """Plain-language post-mortem of a lost run: how it failed, on what, where."""
    tel: Telemetry = world.telemetry          # type: ignore[attr-defined]
    coverage = world.coverage()               # type: ignore[attr-defined]
    kinds = tel.kind_summary()
    nodes = tel.node_summary()

    if world.health <= 0:                      # type: ignore[attr-defined]
        cause = "Latency collapse — queues aged past the grace period and bled your health."
    else:
        cause = "Dropped too many alerts — uncovered kinds and queue overflows piled up."
    lines: list[str] = []

    # worst kinds by total leaked, flagging coverage gaps vs. overwhelmed
    leaky = sorted(kinds.items(), key=lambda kv: kv[1].leaked, reverse=True)
    for kind, kw in leaky[:3]:
        if kw.leaked == 0:
            continue
        tag = "no consumer (coverage gap)" if kind not in coverage else "covered but overwhelmed"
        p95 = tel.latency[kind].percentile(95) if kind in tel.latency else 0.0
        lat = f", p95 dwell {p95:.1f}s" if p95 else ""
        lines.append(f"{kind}: {kw.leaked} leaked / {kw.spawned} — {tag}{lat}")

    # worst bottleneck nodes by overflow then peak queue then dwell
    busy = sorted(nodes.items(),
                  key=lambda kv: (kv[1].overflow_drops, kv[1].peak_queue, kv[1].dwell_seconds),
                  reverse=True)
    for node, nw in busy[:2]:
        if nw.peak_queue == 0 and nw.overflow_drops == 0:
            continue
        lines.append(f"node {node}: peak queue {nw.peak_queue}, "
                     f"{nw.overflow_drops} overflow drops (bottleneck)")

    if not lines:
        lines.append("No telemetry captured — failed before traffic built up.")
    return Debrief(cause=cause, lines=lines)
