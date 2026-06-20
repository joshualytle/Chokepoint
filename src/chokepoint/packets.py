"""Data packets — the things that flood the pipeline.

Each packet has a ``kind`` (an alert/data type). A turret can only process the
kinds its gun *accepts*, so the core puzzle is coverage: do your placed turrets
collectively accept every kind that shows up, with enough throughput to absorb
bursts? Uncovered kinds flood straight through to the exit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# kind -> presentation + tooltip text. Colors are RGB.
KINDS: dict[str, dict] = {
    "auth":       {"color": (127, 179, 255), "desc": "Authentication events: logins and MFA."},
    "ids":        {"color": (242, 166, 90),  "desc": "Intrusion-detection signatures and scans."},
    "dns":        {"color": (56, 225, 176),  "desc": "DNS query and tunneling anomalies."},
    "cloudtrail": {"color": (200, 140, 255), "desc": "Cloud API audit events (CloudTrail-style)."},
    "endpoint":   {"color": (229, 85, 110),  "desc": "Endpoint/EDR detections — heavy to process."},
    "firewall":   {"color": (174, 196, 214), "desc": "Firewall allow/deny and port scans."},
    "email":      {"color": (235, 215, 90),  "desc": "Email-security / phishing-report alerts."},
    "waf":        {"color": (0, 200, 200),    "desc": "Web-app firewall / injection hits."},
    "vuln":       {"color": (255, 120, 200),  "desc": "Vulnerability-scan findings to triage."},
}
KIND_LIST: list[str] = list(KINDS)


@dataclass
class Packet:
    """One unit of alert traffic flowing through the topology.

    ``volume`` is how much processing it needs; a serving turret chips it down
    each shot until handled. A packet is either *in transit* on an edge
    (``moving_to`` set, ``seg_pos`` = distance along it) or *queued* at node
    ``at`` (``moving_to`` is None), where ``wait`` accrues its dwell time. Reach
    the sink unhandled, sit queued too long, or overflow a queue -> trouble.
    """

    kind: str
    volume: float
    maxvol: float
    speed: float
    at: str                     # node id the packet is queued at / departing from
    moving_to: str | None = None  # node id it's traveling toward; None = queued
    seg_pos: float = 0.0        # distance covered along the current edge
    wait: float = 0.0           # seconds spent queued at the current node (dwell)
    dead: bool = False
    handled: bool = False


# Wave streams: (kind, count, gap_seconds, delay_seconds). Tight gaps + high
# counts = a burst/flood.
#
# The waves are a curriculum, generated below. Kinds are introduced one at a
# time in INTRO_ORDER, and each gets three escalating sub-waves — slow, fast,
# then faster-with-a-burst — so you learn to handle a rising rate and a spike
# before the next type arrives. Previously-introduced kinds keep trickling in as
# background pressure, so coverage has to be maintained, not abandoned. A kind is
# only introduced once its handling gun has unlocked.

# kind -> the order it enters the curriculum (its handler unlocks earlier)
INTRO_ORDER: list[str] = ["auth", "ids", "dns", "firewall", "email",
                          "cloudtrail", "endpoint", "waf", "vuln"]
SUBWAVES = 3  # per kind: slow, fast, faster+burst


def _stage_wave(i: int) -> list[tuple[str, int, float, float]]:
    """The i-th curriculum wave: one focus kind escalating, prior kinds behind it."""
    stage, sub = divmod(i, SUBWAVES)
    focus = INTRO_ORDER[stage]
    if sub == 0:                                   # slow: gentle steady stream
        groups = [(focus, 10, 0.70, 0.0)]
    elif sub == 1:                                 # fast: higher rate
        groups = [(focus, 12, 0.45, 0.0)]
    else:                                          # faster + a burst spike
        groups = [(focus, 12, 0.32, 0.0), (focus, 10, 0.12, 3.5)]
    for prior in INTRO_ORDER[:stage]:              # background pressure
        groups.append((prior, 6, 0.80, 1.5))
    return groups


WAVES: list[list[tuple[str, int, float, float]]] = [
    _stage_wave(i) for i in range(len(INTRO_ORDER) * SUBWAVES)
]


def synth_wave(i: int) -> list[tuple[str, int, float, float]]:
    """Endless scaling after the handcrafted waves run out."""
    return [
        ("ids", 12 + i, 0.3, 0.0),
        ("endpoint", i // 2, 1.0, 1.0),
        ("cloudtrail", i, 0.4, 2.0),
        ("email", i, 0.5, 1.5),
        ("auth", 10 + i, 0.4, 0.0),
    ]


# --------------------------------------------------------------------------- #
#  Difficulty strategies — load profiles for the next wave
# --------------------------------------------------------------------------- #
#
# Each strategy is a pure function (wave_idx, leaked) -> spawn groups, where
# ``leaked`` is how many of each kind have leaked so far. Overkill and Adaptive
# transform the Easy baseline, so kinds stay introduced sanely (the curated
# WAVES still drive what appears when) and Adaptive only amplifies kinds that
# have actually shown up. A "Wave" is a list of (kind, count, gap, delay) groups.

Wave = list[tuple[str, int, float, float]]
WaveStrategy = Callable[[int, dict[str, int]], Wave]


def easy_wave(wave_idx: int, leaked: dict[str, int]) -> Wave:
    """Steady ramp: the curated intro, then the gentle endless tail. The default."""
    return WAVES[wave_idx] if wave_idx < len(WAVES) else synth_wave(wave_idx)


def overkill_wave(wave_idx: int, leaked: dict[str, int]) -> Wave:
    """Crank the Easy baseline: ~60% more volume per group and tighter gaps."""
    return [
        (kind, max(1, round(count * 1.6)), gap * 0.6, delay)
        for kind, count, gap, delay in easy_wave(wave_idx, leaked)
    ]


def calm_wave(wave_idx: int, leaked: dict[str, int]) -> Wave:
    """Gentler than Easy — fewer packets, looser gaps. A learning pace."""
    return [
        (kind, max(1, round(count * 0.6)), gap * 1.4, delay)
        for kind, count, gap, delay in easy_wave(wave_idx, leaked)
    ]


def adaptive_wave(wave_idx: int, leaked: dict[str, int]) -> Wave:
    """Press the weak spot: add a burst of whichever kind has leaked the most.

    If nothing has leaked yet, it's just the Easy baseline. Once a kind starts
    slipping through, the next wave concentrates a tight burst of it — the load
    generator probing your coverage gap.
    """
    base = easy_wave(wave_idx, leaked)
    worst_leak = max(leaked.values(), default=0)
    if worst_leak <= 0:
        return base
    # max(..., key=leaked.get) picks the kind name with the highest leak count
    worst_kind = max(leaked, key=lambda k: leaked[k])
    burst = (worst_kind, 8 + wave_idx, 0.25, 0.5)
    return [*base, burst]


DIFFICULTIES: dict[str, WaveStrategy] = {
    "easy": easy_wave,
    "adaptive": adaptive_wave,
    "overkill": overkill_wave,
    "calm": calm_wave,
}
DIFFICULTY_LIST: list[str] = list(DIFFICULTIES)
