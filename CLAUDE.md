# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

Chokepoint (package `chokepoint`) is a typed-alert tower-defense for learning
Python. Packets are typed alerts that flow a topology and queue at nodes;
turrets are typed consumers that only process the kinds their gun accepts. It
teaches the skills behind high-volume alert pipelines — **typed routing,
consumer specialization/coverage, queue/latency backpressure, and
flood/burst handling**.

## Who I'm working with

An experienced security/DevOps engineer **learning Python** for an AWS Lambda +
Python alert-pipeline role. So:

- Explain a Python idiom briefly the first time it appears (decorators, frozen
  dataclasses, `frozenset`, comprehensions, `key=` functions, threading).
- Favor clear over clever. This is a learning codebase.
- Name the pipeline parallel when natural: turrets are typed consumers, a
  coverage gap is an unhandled event type, a burst that exceeds combined
  throughput is per-type backpressure.
- Don't over-engineer. Small, reviewable changes; say what each does and why.

## Architecture

```
packets.py     alert KINDS + WAVES (flood/burst), plus difficulty strategies
               (easy/adaptive/overkill) in the DIFFICULTIES registry. Pure data.
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
metrics.py     Telemetry — pure observability backend. World feeds it events +
               per-wave samples; aggregates KindFlow/NodeLoad/Latency(Histogram)/
               Trend/Efficiency. summarize_failure() -> incident post-mortem.
maps.py        Graph topology: Node + directed adj, source/sink, edge_len,
               nearest_node. Phase-1 maps are single trunks (linear chains).
simulation.py  World.step() — flow network: packets queue at nodes, turrets
               drain the queue they're bound to; dual failure (overflow/sink
               LOSS -> leaks, dwell LATENCY -> health). Owns Bank + wave income.
               coverage_gaps(), leveling. NO pygame. Fully tested.
editor.py      ArsenalEditor — pure placement/economy state machine: select/queue,
               place/equip/remove by click coords, seed_purchase a loadout. Tested.
loadout.py     build_loadout(unlocked, slots) -> [Turret]. The player edits this.
render.py      pygame: draw, tooltips, map switch, F5 hot-reload, L = LLM help,
               E = in-game placement editor (drives ArsenalEditor).
llm_assist.py  optional local-LLM diagnostics over stdlib urllib; degrades to a
               friendly message if no model is running. localhost only.
```

Dependency direction: packets/arsenal/maps → economy → simulation →
(editor, loadout, llm_assist) → render.

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

Done: in-game placement editor (`editor.py`), credit economy (`economy.py`),
difficulty strategies incl. adaptive waves (`packets.DIFFICULTIES`).

**Direction — topological v2.** The game is pivoting from a spatial tower-defense
(turrets target by x/y range along a fixed polyline) toward a *flow network*:
one map that grows **branches** you design; **gates** that route/pre-filter
packets by kind (Lambda-style) between branches; turrets that **drain a node's
queue** rather than target by range; and **queue dwell that bleeds health**
(SLA/backpressure) as the failure mode instead of leak-at-exit. Build it in
phases behind the pure/tested core: graph+queues → turrets-serve-queues → gates
→ latency-drain → branch-building UI. The economy/Bank/editor state machine and
registries all carry over; spatial `range` fades.

Smaller wins still open: more content (guns/modules/kinds) via the registries;
richer synergies / clearer unlock UI.

Touch the pure modules for behavior (with tests), then render.py for UI. Keep
them separable.
