# SETUP — Packet Defense

A typed-alert tower defense for learning Python. **Packets** are alerts of
different kinds that flood a map; **turrets** are typed consumers that can only
process the kinds their **gun** accepts. You win by composing guns, modules, and
placements so your coverage and throughput absorb the flood.

## Install & run

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"             # or: pip install -r requirements.txt
python -m factory_defense           # launch
make check                          # ruff + mypy + 15 tests, all green
```

Requires Python 3.11+ and pygame 2.6+.

## Controls

| Key      | Action                                   |
|----------|------------------------------------------|
| `[` `]`  | previous / next map                      |
| `R`      | reset the run                            |
| `P`      | pause / resume                           |
| `F5`     | reload your `loadout.py` (after editing) |
| `L`      | ask your local LLM for help (optional)   |
| hover    | a turret or legend swatch → tooltip      |

## The one file you edit: `loadout.py`

`src/factory_defense/loadout.py` is where you place and equip turrets — "all in
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

A turret's position lives on the object (`Turret(x, y, gun=...)`), so placement
is just data you set. Different maps route packets differently, so you'll
reposition turrets when you switch maps.

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

The core puzzle is **coverage**: if no placed turret accepts a kind that shows
up, every packet of that kind leaks. Watch the per-kind table and the
`COVERAGE GAP` warning, then add a turret whose gun accepts the missing kind.

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
