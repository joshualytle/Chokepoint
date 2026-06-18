# SETUP — Chokepoint

A typed-alert tower defense for learning Python. **Packets** are alerts of
different kinds that flood a map; **turrets** are typed consumers that can only
process the kinds their **gun** accepts. You win by composing guns, modules, and
placements so your coverage and throughput absorb the flood.

## Install & run

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"             # or: pip install -r requirements.txt
python -m chokepoint           # launch
make check                          # ruff + mypy + 15 tests, all green
```

Requires Python 3.11+ and pygame 2.6+.

## Controls

| Key      | Action                                   |
|----------|------------------------------------------|
| `[` `]`  | previous / next map                      |
| `R`      | reset the run                            |
| `P`      | pause / resume                           |
| `E`      | toggle the in-game placement editor      |
| `M`      | toggle the metrics dashboard             |
| `D`      | cycle difficulty (easy/adaptive/overkill)|
| `F5`     | reload your `loadout.py` (after editing) |
| `L`      | ask your local LLM for help (optional)   |
| hover    | a turret or legend swatch → tooltip      |

## Two ways to build a loadout

You can compose turrets **in the file** (`loadout.py`, below) or **in-game**
with the placement editor — press `E`. In the editor:

- Click a gun in the palette (or press `1`–`9`) to select it, click module rows
  to queue upgrades onto it, then **left-click the map** to place.
- **Left-click an existing turret** to equip your queued modules onto it.
- **Right-click** a turret to remove it (full refund).

Both paths run through the same budget: `loadout.py` is your *initial paid
build*, and the editor spends from the same credits for changes.

## Credits — design under a budget

Every gun and module has a credit **cost** (shown in tooltips and the palette).
You start with a fixed budget and **earn more each time you clear a wave**, with
income scaling up as waves intensify — so your defenses scale with the threat.
The constraint is *peak* deployment: everything live at once must fit your
balance. Removing a turret refunds it in full, so you're free to rearrange — the
puzzle is covering every kind with enough throughput **for the fewest credits**.

This is the pipeline lesson in disguise: you don't get unlimited consumers or
throughput, so you size typed consumers to the load instead of over-provisioning.

## Difficulty (press `D` to cycle)

Three load profiles for the incoming flood:

- **easy** — a steady ramp; the curated intro waves then a gentle endless tail.
- **adaptive** — presses your weak spot: the next wave piles on whichever kind
  has leaked the most so far. A load generator probing your coverage gap.
- **overkill** — more volume and tighter bursts across the board.

Cycling difficulty resets the run.

## Metrics & the failure debrief

Every run collects telemetry — the observability half of a pipeline. Press `M`
for the dashboard: peak queue depth per node (red = it overflowed), handled vs.
leaked per kind, a health trend line, and `cost / handled` (your
over-provisioning KPI — spam turrets and it climbs).

When you lose, the screen shows an **incident post-mortem**: whether latency or
drops killed you, which kinds leaked (and whether they had *no consumer* vs.
were *covered but overwhelmed*), and which nodes were the bottlenecks. Read it
like a real alert-pipeline incident review, then fix the named weak spot.

## The one file you edit: `loadout.py`

`src/chokepoint/loadout.py` is where you place and equip turrets — "all in
Python." Build a gun from the arsenal, attach unlocked modules, set its position,
return the list. Edit it, then press `F5` in-game to reload.

```python
from .arsenal import MODULE_LIBRARY, Turret, make_gun

def build_loadout(unlocked, slots):
    sieve = make_gun("sieve")                 # accepts auth, dns
    if "range+" in unlocked:
        sieve.attach(MODULE_LIBRARY["range+"])
    return [
        Turret(*slots[0], gun=sieve),
        Turret(*slots[1], gun=make_gun("scatter")),   # accepts ids, firewall
    ]
```

A turret's position lives on the object (`Turret(x, y, gun=...)`). The map is a
graph of **nodes** (junctions where packets queue) joined by edges; when a
turret is placed it **binds to the nearest node** and drains that node's queue
for the kinds it accepts. Place a consumer where its kind actually piles up.

## The arsenal (drop-in objects)

- **Guns** have a *static* fire rate and a set of packet kinds they `accept`.
  Built-ins: `sieve` (auth/dns), `scatter` (ids/firewall), `auditor`
  (cloudtrail), `lance` (endpoint). Add your own with the `@register_gun`
  decorator in `arsenal.py` and it appears everywhere automatically.
- **Modules** are upgrades you `attach()` to a gun — more range, more processing
  per shot, or coverage of an extra kind. You don't upgrade fire rate; you unlock
  modules by reaching later waves.
- **Synergies** trigger when you place a specific pair of guns together (e.g.
  `sieve` + `auditor` = "Correlation", +25% throughput to both).

The core puzzle is **coverage + latency**. Two ways to lose:

- **Loss (leaks):** a kind no turret accepts flows untouched to the exit, and a
  node whose queue overflows its capacity drops the excess. Too many drops ends
  the run (watch `leaks` and the `COVERAGE GAP` warning).
- **Latency (health):** packets that sit queued past a short grace period bleed
  your `health` — the SLA/backpressure failure. A node whose turrets can't keep
  up with its inflow backs up and drains health even though its kind *is*
  covered. The fix isn't always "another turret" — it's enough throughput, the
  right gun, or a module, at the node that's backing up.

Watch the per-kind table, the node queue counts, and the health bar, then fix
the bottleneck.

## Optional: local LLM help

If you run a local model, press `L` and the game hands it the current state
(coverage gaps, per-kind leaks, your turrets) and asks how to fix your loadout.
It runs off-thread, so the game never freezes, and if no model is running you
just get a friendly note — nothing breaks.

Point it at your server with environment variables (no secrets in code):

```bash
# Ollama (default)
ollama run llama3.1
# the game uses http://localhost:11434/api/generate automatically

# LM Studio / llama.cpp / any OpenAI-compatible server:
export FD_LLM_URL="http://localhost:1234/v1/chat/completions"
export FD_LLM_MODEL="your-model-name"
```

It only ever talks to your localhost.
