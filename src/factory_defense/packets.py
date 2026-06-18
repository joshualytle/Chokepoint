"""Data packets — the things that flood the pipeline.

Each packet has a ``kind`` (an alert/data type). A turret can only process the
kinds its gun *accepts*, so the core puzzle is coverage: do your placed turrets
collectively accept every kind that shows up, with enough throughput to absorb
bursts? Uncovered kinds flood straight through to the exit.
"""

from __future__ import annotations

from dataclasses import dataclass

# kind -> presentation + tooltip text. Colors are RGB.
KINDS: dict[str, dict] = {
    "auth":       {"color": (127, 179, 255), "desc": "Authentication events: logins and MFA."},
    "ids":        {"color": (242, 166, 90),  "desc": "Intrusion-detection signatures and scans."},
    "dns":        {"color": (56, 225, 176),  "desc": "DNS query and tunneling anomalies."},
    "cloudtrail": {"color": (200, 140, 255), "desc": "Cloud API audit events (CloudTrail-style)."},
    "endpoint":   {"color": (229, 85, 110),  "desc": "Endpoint/EDR detections — heavy to process."},
    "firewall":   {"color": (174, 196, 214), "desc": "Firewall allow/deny and port scans."},
}
KIND_LIST: list[str] = list(KINDS)


@dataclass
class Packet:
    """One unit of alert traffic. ``volume`` is how much processing it needs;
    turrets chip it down with each shot. Reaches the exit unhandled -> a leak."""

    kind: str
    volume: float
    maxvol: float
    speed: float
    d: float = 0.0
    dead: bool = False
    handled: bool = False


# Wave streams: (kind, count, gap_seconds, delay_seconds).
# Tight gaps + high counts = a burst/flood. Kinds are introduced gradually so
# you can adapt your loadout; the tool to handle each kind unlocks in time
# (see arsenal.UNLOCKS).
WAVES: list[list[tuple[str, int, float, float]]] = [
    [("auth", 10, 0.6, 0.0)],
    [("auth", 8, 0.6, 0.0), ("ids", 8, 0.6, 1.0)],
    [("ids", 10, 0.5, 0.0), ("dns", 8, 0.7, 1.5)],
    [("firewall", 12, 0.4, 0.0), ("ids", 20, 0.18, 2.0)],            # ids burst
    [("cloudtrail", 10, 0.6, 0.0), ("auth", 10, 0.5, 1.0), ("dns", 8, 0.6, 2.0)],
    [("endpoint", 6, 1.2, 0.0), ("ids", 14, 0.3, 1.0),
     ("cloudtrail", 10, 0.5, 2.0), ("firewall", 16, 0.25, 3.0)],     # mixed flood
]


def synth_wave(i: int) -> list[tuple[str, int, float, float]]:
    """Endless scaling after the handcrafted waves run out."""
    return [
        ("ids", 12 + i, 0.3, 0.0),
        ("endpoint", i // 2, 1.0, 1.0),
        ("cloudtrail", i, 0.4, 2.0),
        ("auth", 10 + i, 0.4, 0.0),
    ]
