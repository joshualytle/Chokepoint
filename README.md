# Chokepoint

[![CI](https://github.com/joshualytle/Chokepoint/actions/workflows/ci.yml/badge.svg)](https://github.com/joshualytle/Chokepoint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-f2c85a?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/joshua1lytp)

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

### Play in the browser — `web/`

There's a **native-web** version with a crisp HTML/canvas UI and a real code
editor (CodeMirror) — no install for players. The whole Python core + your
`loadout.py` run in the browser via [Pyodide](https://pyodide.org/); player code
is **sandboxed** (`safety.py`) so it can't import arbitrary modules or reach the
network/DOM. The desktop build is unchanged (`python -m chokepoint`).

```bash
python serve_native.py               # http://localhost:8001 (packages the core for Pyodide)
```

#### Hosting the web-native app

The `web/` app is **pure static files** with **no backend** — the Python runs in
the visitor's browser via Pyodide (loaded from a CDN, along with CodeMirror), and
player code is sandboxed. So it can be served by **any static host**, not just
GitHub:

- **GitHub Pages** — automated by `.github/workflows/pages.yml`: pushing to `main`
  packages the core and deploys `web/`. One-time setup: **Settings → Pages → Build
  and deployment → Source: *GitHub Actions***. Publishes to
  `https://<user>.github.io/<repo>/`.
- **Netlify / Vercel / Cloudflare Pages / S3 / nginx / your own box** — serve the
  `web/` folder. Two caveats:
  1. Include **`web/chokepoint.zip`** (the packaged Python core). It's
     git-ignored, so build it first with
     `python -c "import serve_native; serve_native.build_package()"` (or give the
     host that as a build command), then deploy `web/`.
  2. Serve over **http(s)**, not `file://`, and visitors need internet on first
     load for the Pyodide/CodeMirror CDNs.

For a fully self-contained/offline build (no CDN dependencies), vendor Pyodide and
CodeMirror into `web/` and point the `<script>` tags at the local copies.

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
web/              # native-web app (Pyodide + HTML/canvas); serve_native.py serves it
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

## Contributing & community

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and
the ground rules, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for how we work
together. Found a security issue? Please report it privately per
[SECURITY.md](SECURITY.md). Changes of note are tracked in
[CHANGELOG.md](CHANGELOG.md).

If the project helped you learn something, you can
[buy me a coffee](https://buymeacoffee.com/joshua1lytp) ☕ — it keeps the work
open-source and free. Thank you!

## License & attribution

Chokepoint is released under the [MIT License](LICENSE) — you're free to **use,
copy, modify, and distribute** it, including in your own projects, courses, or
products, and at no cost. In plain terms, the license asks one thing in return:

> **Keep the attribution.** Retain the copyright notice and the MIT license text
> (the `LICENSE` file) in any copy or substantial portion of the software.

That's the whole deal — credit stays, and the software is provided "as is,"
without warranty. If you fork it or build something on top, a link back to
[this repository](https://github.com/joshualytle/Chokepoint) is appreciated but
not required; a [CITATION.cff](CITATION.cff) is included if you'd like to cite it
formally (GitHub renders a "Cite this repository" button from it).

Cloning, forking, and starring are all welcome. If you're using it to teach or
learn, I'd love to hear about it.
