# Chokepoint

A typed-alert tower-defense for learning Python. Alerts of different **kinds**
(`auth`, `ids`, `dns`, `firewall`, `email`, `cloudtrail`, `endpoint`, `waf`,
`vuln`) flow a pipeline and **queue at nodes**. **Turrets** are typed consumers —
each drains a node's queue but only for the kinds its **gun** accepts. You hold
the line by composing guns, modules, **gates** (typed routers), and
**quelimiters** (rate limiters) across a topology you can design yourself.

It's a sandbox for the skills behind high-volume alert pipelines — **typed
routing, consumer specialization, coverage, queue/latency backpressure, and
flood/burst handling** — as a game.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m chokepoint     # play
make check               # ruff + mypy + tests  (no make on Windows? run the three directly)
```

Press **`H`** in-game for the full controls + legend; a short walkthrough shows
on first launch. See `SETUP.md` for details and optional local-LLM help.
Requires Python 3.11+ and pygame 2.6+.

## Two ways to lose

- **Loss (leaks):** a kind no turret accepts flows to the exit, or a node's
  queue overflows.
- **Latency (health):** alerts that sit queued too long age out and bleed your
  health — backpressure made real.

A live **COACH** line tells you the most important thing to fix; the metrics
dashboard (`M`) shows queues, per-kind flow, a health trend, and the full
coaching list.

## What you can build

- **Editor (`E`)** — buy and place turrets/gates/limiters (drag-and-drop), equip
  modules; everything runs on a credit budget that grows as you clear waves.
- **Build mode (`T`)** — design the topology itself: add nodes, draw edges
  (cycle-checked), remove. Gates route kinds down the branch that handles them.
- **Code (`C`)** — edit `loadout.py` in-app (highlighted, undo, validated apply)
  or externally + `F5`. `S` saves your build *and* custom map to resume later.
- **Sandbox (`K`)** — free credits to experiment.

## Project layout

```
src/chokepoint/
  packets.py      # alert kinds + the wave curriculum + difficulty strategies
  arsenal.py      # drop-in guns, modules, turrets, synergies, unlocks, costs
  economy.py      # Bank: the credit budget
  gates.py        # Gate: typed router at a fork
  limiter.py      # Quelimiter: rate limiter / burst buffer
  maps.py         # Graph topology (editable); built-in maps
  simulation.py   # World: queues, typed processing, dual failure (NO pygame; tested)
  metrics.py      # Telemetry + failure debrief
  hints.py        # the in-game coach
  editor.py       # pure placement/economy state machine
  codebuffer.py   # text buffer for the in-app code editor
  syntax.py       # tiny tokenizer for editor highlighting
  scores.py       # high-score persistence
  loadout.py      # YOU EDIT THIS: place + equip turrets (and gates/limiters) in Python
  render.py       # pygame UI (the only module with pygame)
tests/            # headless tests for everything but render
```

Everything except `render.py` is pygame-free and tested headless; rendering only
reads simulation state.

## The core idea

A turret's gun `accepts` a set of kinds and drains the queue at the node it sits
on. Uncovered kinds leak; covered-but-overwhelmed nodes back up, age, and bleed
health. Gates pre-filter traffic to the right consumer (Lambda/EventBridge
style); quelimiters smooth bursts (but their buffer is finite, so sustained load
still needs throughput). Fire rate is static — you scale with modules, more
consumers, routing, and synergies. That's the alert-pipeline lesson, playable.
