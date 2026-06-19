"""Quelimiter — a rate limiter / buffer you place on a node to tame bursts.

A turret's throughput is capped by its static fire rate, so a burst piling onto
its node overflows (drops) and ages (bleeds health). A quelimiter placed
upstream absorbs the spike: it buffers unserved packets (a large capacity, and
buffered packets don't bleed health — it's an intentional buffer, not an SLA
breach) and *releases them onward at a fixed rate*, smoothing a burst into a
steady stream the downstream consumer can keep up with.

The catch — and the lesson — is the buffer is finite and the release rate is
fixed: a limiter smooths *bursts*, but *sustained* overload still overflows it.
For sustained load you need throughput (more turrets / damage), not just a
buffer. That's rate-limiting vs. scaling concurrency, the real backpressure call.

Pure data + a token-bucket release; placement/cost handled like turrets & gates.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LIMITER_COST = 110
LIMITER_BUFFER_CAP = 24      # how many packets it can hold (vs the default node cap)
LIMITER_RELEASE_RATE = 4.0   # packets/second released onward


@dataclass
class Limiter:
    """Meters pass-through flow at a node: buffer big, release at a steady rate."""

    x: float
    y: float
    release_rate: float = LIMITER_RELEASE_RATE
    buffer_cap: int = LIMITER_BUFFER_CAP
    cost: int = DEFAULT_LIMITER_COST
    node: str = ""        # node it sits on (assigned by the simulation)
    id: str = ""          # assigned by the simulation
    tokens: float = 0.0   # token-bucket credit; 1 token releases 1 packet

    def refill(self, dt: float) -> None:
        """Accrue release credit, capped at ~1s worth so it can't hoard a burst."""
        self.tokens = min(self.tokens + self.release_rate * dt, self.release_rate)
