# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

Packet Defense (package name `factory_defense`, historical) is a typed-alert
tower-defense for learning Python. Packets are typed alerts that flood a map;
turrets are typed consumers that only process the kinds their gun accepts. It
teaches the skills behind high-volume alert pipelines — **typed routing,
consumer specialization/coverage, and flood/burst handling**.

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
packets.py     alert KINDS + WAVES (flood/burst). Pure data.
arsenal.py     Gun (static fire_rate, accepts set), Module (attach to upgrade),
               Turret (carries its x/y), registries (@register_gun, register_module),
               SYNERGIES, unlocked_at(wave). The drop-in library.
maps.py        GameMap owns path geometry + pos_at(). MAPS dict, multiple maps.
simulation.py  World.step() — typed processing, per-kind KindStat, coverage_gaps(),
               leveling. NO pygame. Fully tested.
loadout.py     build_loadout(unlocked, slots) -> [Turret]. The player edits this.
render.py      pygame: draw, tooltips, map switch, F5 hot-reload, L = LLM help.
llm_assist.py  optional local-LLM diagnostics over stdlib urllib; degrades to a
               friendly message if no model is running. localhost only.
```

Dependency direction: packets/arsenal/maps → simulation → (loadout, llm_assist) → render.

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
make check     # ruff + mypy + pytest (15 tests)
```

## Roadmap (good next tasks)

1. **In-game arsenal/placement editor** so the player composes loadouts without
   editing the file (currently loadout.py + F5). Teaches event handling + state.
2. **More content**: new guns/modules/maps via the registries; new packet kinds.
3. **Adaptive waves**: synthesize the next wave from which kinds leaked most —
   pressure the player's weakest coverage. Mostly dict analysis.
4. **Richer synergies / clearer unlock UI.**

Touch the pure modules for behavior (with tests), then render.py for UI. Keep
them separable.
