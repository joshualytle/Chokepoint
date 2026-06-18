# HANDOFF — Chokepoint

Kickoff briefing for a Claude Code session. Open the repo and start with:
**"Read HANDOFF.md and CLAUDE.md, verify the build with `make check`, then
propose next steps."**

## What this is

A typed-alert tower-defense for learning Python. Packets are typed alerts that
flood a map; turrets are typed consumers that only process the kinds their gun
accepts. The puzzle is coverage + throughput — the same shape as routing a
high-volume alert pipeline. Full rationale in `CLAUDE.md`; how to play in `SETUP.md`.

## How I want to work (learning contract)

I'm an experienced security/DevOps engineer learning Python for an AWS Lambda +
Python alert-pipeline role. Explain idioms the first time, favor clear code,
name the pipeline parallels, make small reviewable changes, don't over-engineer.

## Current state — VERIFIED

- `python -m chokepoint` launches the game (desktop, pygame).
- `make check` is green: **ruff clean, mypy clean, 15 tests passing.**
- Pure logic (packets/arsenal/maps/simulation) has no pygame and is tested headless.
- `loadout.py` is the player-edited file; `F5` hot-reloads it in-game.
- `llm_assist.py` gives optional local-LLM help; absent a model it degrades cleanly.

Verify before changing anything:

```bash
python -m venv .venv && source .venv/bin/activate
make install
make check        # expect: ruff clean, mypy clean, 15 passed
make run          # optional
```

## Guardrails — don't break these

1. Pure modules stay free of pygame and never touch a display.
2. Fire rate is static; modules never change it (there's a test).
3. Behavior changes get tests.
4. Guns/modules are drop-in via the registries.
5. `llm_assist` stays optional, stdlib-only, localhost-only, never raises into the loop.

## Backlog (rough priority)

1. **In-game arsenal/placement editor.** Compose and place turrets via the UI
   instead of editing `loadout.py`. *Acceptance:* place/equip/remove turrets in
   game, existing loadout path still works, new tests, `make check` green.
   *Teaches:* event handling, UI state, mapping clicks to object positions.
2. **Adaptive waves.** Generate the next wave from which kinds leaked most.
   *Acceptance:* difficulty visibly targets weak coverage; test asserts the link.
3. **More content** (guns/modules/maps/kinds) via the registries.
4. **Synergy + unlock UI polish.**

## Suggested first prompt after verifying

> "Let's do backlog item 1 — the in-game placement editor. Plan it first, point
> out the Python concepts I'll meet, then build it in small steps with tests.
> Keep the pure modules free of pygame."
