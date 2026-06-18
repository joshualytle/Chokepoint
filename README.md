# Packet Defense

A typed-alert tower-defense for learning Python. **Packets** are alerts of
different kinds (`auth`, `ids`, `dns`, `cloudtrail`, `endpoint`, `firewall`) that
flood a map. **Turrets** are typed consumers — each only processes the kinds its
**gun** accepts. You hold the line by composing guns, modules, and placements so
your coverage and throughput absorb the flood and the bursts.

It's a sandbox for the skills behind high-volume alert pipelines — **typed
routing, consumer specialization, coverage, and flood/burst handling** — as a game.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m factory_defense     # play
make check                    # ruff + mypy + 15 tests
```

See `SETUP.md` for controls, the arsenal, editing your loadout, and optional
local-LLM help. Requires Python 3.11+ and pygame 2.6+.

## Project layout

```
src/factory_defense/
  packets.py      # alert kinds + wave definitions (flood/burst)
  arsenal.py      # drop-in guns, modules, turrets, synergies, unlocks
  maps.py         # multiple maps; each owns its path math
  simulation.py   # World: typed processing, per-kind metrics, leveling (NO pygame; tested)
  loadout.py      # YOU EDIT THIS: place + equip turrets in Python
  render.py       # pygame UI: tooltips, map switching, hot-reload, LLM helper
  llm_assist.py   # optional local-LLM diagnostics (stdlib only, graceful)
  __main__.py
tests/            # headless tests for simulation + arsenal
```

The simulation has no pygame dependency, so the logic runs and tests headless;
rendering only reads simulation state.

## The core idea

Each turret's gun `accepts` a set of packet kinds. A turret only processes
packets of those kinds in its range. If no placed turret accepts a kind that
appears, every packet of that kind leaks — that's the alert-pipeline lesson:
typed consumers must collectively cover the event mix, with enough throughput per
type to survive bursts. Fire rate is static; you scale by unlocking modules and
pairing guns for synergies as you reach later waves.

## Where it's going

- More guns/modules/maps (all drop-in via the registries in `arsenal.py`).
- An in-game arsenal/placement editor (currently you edit `loadout.py` + F5).
- Richer synergies and a clearer unlock/leveling UI.
