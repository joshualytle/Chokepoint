# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

Chokepoint (package `chokepoint`) is a typed-alert tower-defense for learning
Python. Packets are typed alerts that flow a topology and queue at nodes;
turrets are typed consumers that only process the kinds their gun accepts. It
teaches the skills behind high-volume alert pipelines — **typed routing,
consumer specialization/coverage, queue/latency backpressure, and
flood/burst handling**.

## Who this is for

The audience is people **learning Python** — often engineers from ops, security,
or DevOps who know pipelines but are new to the language. So, when contributing:

- Explain a Python idiom briefly the first time it appears (decorators, frozen
  dataclasses, `frozenset`, comprehensions, `key=` functions, threading).
- Favor clear over clever. This is a learning codebase.
- Name the pipeline parallel when natural: turrets are typed consumers, a
  coverage gap is an unhandled event type, a burst that exceeds combined
  throughput is per-type backpressure.
- Don't over-engineer. Small, reviewable changes; say what each does and why.

## Architecture

```
packets.py     alert KINDS (incl. "raw") + Packet.payload + WAVES (flood/burst),
               plus difficulty strategies (calm/easy/adaptive/overkill/ingest)
               in the DIFFICULTIES registry. Pure data.
arsenal.py     Gun (static fire_rate, accepts set, cost), Module (attach to upgrade,
               cost), Turret (carries its x/y), registries (@register_gun,
               register_module), gun_cost(), SYNERGIES, unlocked_at(wave). Drop-in.
economy.py     Bank — credit balance with can_afford/spend/earn. Pure. Shared by
               reference between World (income) and ArsenalEditor (spending).
gates.py       Gate — a typed router placed at a fork; routes kinds to branch
               indices (the Lambda/EventBridge pre-filter). World.autoroute()
               derives routes from the turret layout (content-based routing).
limiter.py     Limiter (quelimiter) — placed on a node; buffers a burst (large
               cap) and releases unserved packets onward at a fixed rate
               (token bucket). Smooths bursts; finite buffer, so sustained
               overload still spills. Rate-limit vs. scale-concurrency.
parsers.py     Parser — placed on a node; decodes a "raw" alert into the kind it
               carries (payload) when the parser handles it. Raw is otherwise
               unconsumable. Pure data + membership test. Drop-in like gates.
metrics.py     Telemetry — pure observability backend. World feeds it events +
               per-wave samples; aggregates KindFlow/NodeLoad/Latency(Histogram)/
               Trend/Efficiency. summarize_failure() -> incident post-mortem.
hints.py       coaching(world) -> prioritized, actionable Hints (the in-game
               coach): names the gun/module to fix a gap, flags bottlenecks, etc.
scores.py      load/save_highscore — tiny stdlib persistence, never raises.
codebuffer.py  TextBuffer — pure text buffer (cursor, edit ops, undo) for the
               in-app code editor.
syntax.py      spans(line) -> tokens for editor highlighting. Pure.
maps.py        Graph topology: Node + directed adj, source/sink, edge_len,
               nearest_node, and editing (add/remove node/edge, cycle-checked,
               copy()). Built-in maps incl. branching (delta/trident/cascade).
simulation.py  World.step() — flow network: packets queue at nodes, _parse
               decodes raw, turrets drain their bound queue, _spill routes an
               overwhelmed node's backlog down a parallel branch (overflow/else);
               dual failure (overflow/sink LOSS -> leaks, dwell LATENCY ->
               health). Owns Bank + wave income. coverage_gaps()/parse_gaps().
               NO pygame. Fully tested.
editor.py      ArsenalEditor — pure placement/economy state machine: select/queue,
               place/equip/remove by click coords, seed_purchase a loadout. Tested.
tutorial.py    Tutorial — scripted, stepped onboarding (manual / event / state
               predicate advance). Pure + tested; render draws the card.
loadout.py     build_loadout(unlocked, slots) -> [Turret] (plus optional
               build_gates/limiters/parsers/topology). The player edits this.
render.py      pygame (the only module with it): draw, tooltips, overlays, the
               editor (E), build mode (T), in-app code editor (C), metrics (M),
               help (H), coach line, sandbox (K), speed (F), scoring, tutorial.
llm_assist.py  optional local-LLM diagnostics over stdlib urllib; degrades to a
               friendly message if no model is running. localhost only.
```

Two front ends: the **desktop** pygame app (`python -m chokepoint` → `render.py`)
and the **native-web** app in `web/` — a Pyodide + HTML/canvas UI where the same
pure core runs in the browser, driven by `web/webgame.py` (a JSON bridge) and
served by `serve_native.py`. Player code (loadout.py) is sandboxed by `safety.py`
(AST allowlist + restricted builtins) before exec, on the web especially. The
glossary lives in `glossary.py`; both UIs reuse the pure hints/tutorial/lessons.

Dependency direction: packets/arsenal/maps → economy/gates/limiter/parsers →
simulation → metrics/hints/editor/loadout/llm_assist → render. tutorial/lessons/
glossary/safety/codebuffer/syntax/scores are leaf helpers used by the UIs.

## Invariants — keep these true

1. `simulation.py` (and packets/arsenal/maps) import no pygame and never touch a
   display. That's what keeps the logic testable.
2. **Fire rate is static.** Modules may change damage/range/coverage, never
   `fire_rate`. There's a test asserting this — keep it passing.
3. Every behavior change gets a test in `tests/`.
4. Guns and modules are drop-in: add via `@register_gun` / `register_module` so
   they flow into tooltips, unlocks, and loadouts automatically.
5. `llm_assist` stays optional, stdlib-only, localhost-only, and never raises
   into the game loop.

## Commands

```bash
make install   # pip install -e ".[dev]"
make run       # launch
make check     # ruff + mypy + pytest
```

## Roadmap (good next tasks)

Done: the flow-network core (graph + queues, turrets drain a node's queue, dwell
bleeds health); in-game placement editor (`editor.py`); credit economy
(`economy.py`); difficulty strategies incl. adaptive waves
(`packets.DIFFICULTIES`); player-designed topology (build mode); gates; parsers
+ the `ingest` difficulty; overflow/`_spill` routing; a native-web app (`web/`,
Pyodide) with a sandbox (`safety.py`); and a guided tutorial (`tutorial.py`).

Open next: keep growing the **training-platform** experience — a teaching coach
that explains *why* + the fix (not just names it), in-editor Python lessons,
contextual "what is this?" help; more content (guns/modules/kinds) via the
registries; richer synergies / clearer unlock UI; browser persistence
(IndexedDB) for saved builds and high scores.

Touch the pure modules for behavior (with tests), then render.py for UI. Keep
them separable.
