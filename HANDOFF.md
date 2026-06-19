# HANDOFF — Chokepoint

Kickoff briefing for a Claude Code session. Open the repo and start with:
**"Read HANDOFF.md and CLAUDE.md, verify the build, then propose next steps."**

## What this is

Chokepoint (package `chokepoint`) is a typed-alert tower-defense for learning
Python, shaped like a real alert pipeline. Packets are typed alerts that flow a
**topology** and **queue at nodes**; turrets are typed consumers that drain the
queue at the node they're bound to, processing only the kinds their gun accepts.
**Gates** placed at forks route each kind down the branch whose consumers can
handle it. You lose two ways: **drops** (uncovered kinds reach the exit, or a
queue overflows) and **latency** (packets sit queued too long and bleed health).
Full rationale in `CLAUDE.md`; how to play in `SETUP.md`.

## How I want to work (learning contract)

I'm an experienced security/DevOps engineer learning Python for an AWS Lambda +
Python alert-pipeline role. Explain idioms the first time, favor clear code,
name the pipeline parallels, make small reviewable changes, don't over-engineer.

## Current state — VERIFIED

- `python -m chokepoint` launches the game (desktop, pygame).
- Build is green: **ruff clean, mypy clean, 84 tests passing.**
- Pure logic (packets/arsenal/economy/gates/maps/simulation/metrics/editor) has
  no pygame and is tested headless; `render.py` is the thin pygame shell.
- In-game editor (`E`) places turrets/gates against a credit budget; `S` saves
  your build to `loadout.py`; `F5` hot-reloads it.
- Telemetry (`metrics.py`) drives the metrics dashboard (`M`) and the failure
  debrief; `H` shows an in-game help/legend overlay.
- `llm_assist.py` gives optional local-LLM help; absent a model it degrades cleanly.

Verify before changing anything (Windows has no `make`; run the tools directly):

```bash
python -m venv .venv && . .venv/Scripts/activate     # or source .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests && mypy src && pytest -q          # = make check elsewhere
python -m chokepoint                                   # optional
```

## Guardrails — don't break these

1. Pure modules (everything but `render.py`) import no pygame and never touch a
   display or the network. That's what keeps the logic testable.
2. Fire rate is static; modules change damage/range/coverage, never `fire_rate`
   (there's a test).
3. Behavior changes get tests in `tests/`.
4. Guns/modules/maps/gates are drop-in: add guns/modules via the registries
   (`@register_gun` / `register_module`), maps via `build_graph`.
5. `llm_assist` stays optional, stdlib-only, localhost-only, never raises into
   the loop. File saves (S) and any future export follow the same "never raise
   into the loop" rule.

## Backlog (rough priority)

Done: placement editor, economy/Bank, difficulty (incl. adaptive), topological
sim (queues + dual failure), telemetry + metrics dashboard + failure debrief,
loadout export, branching maps + gates (autoroute), content (email/quarantine),
help overlay. Project renamed Packet Defense -> Chokepoint.

1. **Tuning pass** — balance queue cap, dwell grace, drain rate, income, costs,
   and the branching maps' difficulty. Needs playtesting with the `M` dashboard;
   *whatever the player reports is the input here.*
2. **Manual gate-routing override UI** — autoroute is the default; let the player
   pin a kind to a branch. The pure `Gate.routes` already supports it.
3. **More content** (guns/modules/kinds/maps) via the registries.
4. **Cross-branch synergies / clearer unlock + synergy UI.**

## Suggested first prompt after verifying

> "Read the latest commits to see what shipped, then let's tune the numbers —
> walk me through what the metrics dashboard is telling us and propose changes
> with tests."
