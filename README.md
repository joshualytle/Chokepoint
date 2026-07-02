# Chokepoint

A typed-alert tower-defense for learning Python. Alerts of different **kinds**
(`auth`, `ids`, `dns`, `firewall`, `email`, `cloudtrail`, `endpoint`, `waf`,
`vuln`) flow a pipeline and **queue at nodes**. **Turrets** are typed consumers —
each drains a node's queue but only for the kinds its **gun** accepts. You hold
the line by composing guns, modules, **gates** (typed routers),
**quelimiters** (rate limiters), and **parsers** (decode *raw* alerts into typed
ones) across a topology you can design yourself.

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

A **guided, step-by-step tutorial** runs on the first launch; press **`H`** any
time for the full controls + legend. See `SETUP.md` for details and optional
local-LLM help. Requires Python 3.11+ and pygame 2.6+.

### Play in the browser

Chokepoint also builds to WebAssembly (via [pygbag](https://pypi.org/project/pygbag/)),
so it runs in any modern browser — no install for players.

```bash
pip install -e ".[web]"
python -m pygbag --build main.py      # emits build/web/
python serve_web.py                   # serve on http://localhost:8000 (and your LAN)
```

The desktop build is unchanged (`python -m chokepoint`); the web build is an
additional target that reuses the same code behind an async render loop.

## Two ways to lose

- **Loss (leaks):** a kind no turret accepts flows to the exit, or a node's
  queue overflows.
- **Latency (health):** alerts that sit queued too long age out and bleed your
  health — backpressure made real.

A live **COACH** line tells you the most important thing to fix; the metrics
dashboard (`M`) shows queues, per-kind flow, a health trend, and the full
coaching list.

## What you can build

The board starts **clean** — you build the pipeline yourself (the tutorial and
coach walk you through it), or press `F5` to load the example `loadout.py`.

- **Editor (`E`)** — buy and place turrets/gates/limiters (drag-and-drop), equip
  modules; everything runs on a credit budget that grows as you clear waves.
- **Build mode (`T`)** — design the topology itself: add nodes, draw edges
  (cycle-checked), remove. Build a **parallel branch** and, when a turret is
  saturated, overload automatically **spills** down it to a backup consumer —
  the "else path" for a full worker.
- **Gates & parsers** — gates route kinds down the branch that handles them
  (Lambda/EventBridge-style pre-filter); parsers decode `raw` alerts into their
  real kind so a consumer can take them (the `ingest` difficulty streams raw).
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
  parsers.py      # Parser: decode raw alerts into their real kind
  maps.py         # Graph topology (editable); built-in maps
  simulation.py   # World: queues, typed processing, spill, dual failure (NO pygame; tested)
  metrics.py      # Telemetry + failure debrief
  hints.py        # the in-game coach
  editor.py       # pure placement/economy state machine
  tutorial.py     # scripted, stepped onboarding (pure; render draws it)
  codebuffer.py   # text buffer for the in-app code editor
  syntax.py       # tiny tokenizer for editor highlighting
  scores.py       # high-score persistence
  llm_assist.py   # optional local-LLM diagnostics (stdlib, localhost-only)
  loadout.py      # YOU EDIT THIS: place + equip turrets (and gates/limiters/parsers) in Python
  render.py       # pygame UI (the only module with pygame)
main.py           # browser (WASM) entry point; serve_web.py serves the build
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

## License

Released under the [MIT License](LICENSE).
