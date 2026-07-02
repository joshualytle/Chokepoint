"""YOUR LOADOUT — edit this file to place and equip turrets.

This is the "all in Python" part. You build turrets from the arsenal, attach
modules you've unlocked, place them by setting position on the object, and the
engine runs them. Reload in-game with F5 after editing.

`build_loadout(unlocked, slots)` receives:
  * unlocked : the set of gun/module names available at the current wave
  * slots    : the current map's suggested (x, y) placement hints

Return a list of Turret objects. Placement lives on each turret (its x, y).
"""

from __future__ import annotations

from .arsenal import MODULE_LIBRARY, Turret, make_gun
from .parsers import Parser


def build_loadout(unlocked: set[str], slots: list[tuple[float, float]]) -> list[Turret]:
    turrets: list[Turret] = []

    # Slot 0 — fast filter for auth/DNS noise. Add the range module once unlocked.
    sieve = make_gun("sieve")
    if "range+" in unlocked:
        sieve.attach(MODULE_LIBRARY["range+"])
    turrets.append(Turret(*slots[0], gun=sieve))

    # Slot 1 — broad coverage for IDS/firewall traffic.
    scatter = make_gun("scatter")
    if "amp" in unlocked:
        scatter.attach(MODULE_LIBRARY["amp"])
    turrets.append(Turret(*slots[1], gun=scatter))

    # Slot 2 — cloud audit specialist once you unlock it (synergizes with sieve).
    if "auditor" in unlocked:
        turrets.append(Turret(*slots[2], gun=make_gun("auditor")))

    # COVERAGE GAP ON PURPOSE: nothing here accepts "endpoint" until you add a
    # lance (unlocks at wave 5). Watch endpoint packets leak, then fix it:
    #
    #     if "lance" in unlocked:
    #         turrets.append(Turret(360, 300, gun=make_gun("lance")))

    return turrets


def build_parsers(unlocked: set[str], slots: list[tuple[float, float]]) -> list[Parser]:
    """Parsers decode raw alerts into typed kinds (the "ingest" difficulty, D).

    A raw alert can't be consumed until a parser placed on its node decodes it.
    Place a parser early (near the source) and list the payload kinds it
    ``handles`` so traffic is typed before it reaches your turrets.

    PARSE GAP ON PURPOSE: this parser doesn't decode "endpoint", so raw endpoint
    alerts stay raw and leak. Add it to handles (or place a second parser) to fix:
    """
    return [
        Parser(*slots[0], handles={"auth", "ids", "dns", "firewall", "email",
                                   "cloudtrail", "waf", "vuln"}),
    ]
