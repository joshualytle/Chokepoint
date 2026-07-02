"""Plain-language help text — the "what is this?" layer.

Two pure tables the UI reads: ``GLOSSARY`` (concept -> one-line definition, shown
in the help overlay) and ``HUD_HELP`` (a HUD element -> tooltip lines, shown when
you hover that stat). Kept here, data-only, so the wording is easy to review and
the render layer stays about drawing.
"""

from __future__ import annotations

# concept -> a one-line, beginner-friendly definition (shown in the H overlay)
GLOSSARY: list[tuple[str, str]] = [
    ("coverage", "A worker (turret) that accepts a given alert type. Uncovered types leak."),
    ("leak", "An alert that exits unhandled, or overflows a full queue. Too many end the run."),
    ("latency / health", "Alerts queued too long bleed your health — an SLA/backpressure failure."),
    ("backpressure", "Inflow faster than a node can process, so its queue grows and ages."),
    ("gate", "A router at a fork: sends each kind down a branch whose workers handle it."),
    ("quelimiter", "Buffers a burst and releases it at a steady rate. The buffer is finite."),
    ("parser", "Decodes a raw alert into its real kind so a worker can consume it (ingest)."),
    ("spill / overflow", "A saturated node routes its backlog down a parallel branch to a backup."),
    ("synergy", "Some gun pairs boost each other's throughput when placed together."),
    ("credits", "Your budget; grows each wave. Placing charges it, removing refunds it."),
]

# a HUD element key -> tooltip lines (first line is the accented title)
HUD_HELP: dict[str, list[str]] = {
    "health": ["HEALTH — your latency budget.",
               "Alerts queued too long drain it; at 0 the pipeline goes down.",
               "Fix: relieve the busiest node (more/faster workers, a limiter, a spill branch)."],
    "leaks": ["LEAKS — alerts lost.",
              "An alert exits unhandled or overflows a full queue. Hit the cap and the run ends."],
    "credits": ["CREDITS (cr) — your budget.",
                "Grows each wave. Spend on turrets/gates/limiters; removing refunds in full."],
    "coverage": ["COVERAGE — are all seen types handled?",
                 "A gap means some type has no worker, so it leaks. The coach names the fix."],
    "kinds": ["Per-type table:  in / ok / leak / now",
              "= arrived / handled / leaked / in the queue right now.",
              "A ! marks an uncovered type (no worker accepts it)."],
}
