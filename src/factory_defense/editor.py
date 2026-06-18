"""In-game arsenal & placement editor — pure state, no pygame.

This is the brain behind the interactive editor. It holds the turrets you are
composing, the gun you're about to place, and any modules queued onto that gun.
``render.py`` is a thin layer that turns mouse clicks and key presses into calls
on this object and draws the result.

That split is deliberate and mirrors ``simulation.py`` (pure, tested) vs.
``render.py`` (pygame): every *decision* lives here where it can be unit-tested
headless, and pygame only feeds events in and draws state out. In alert-pipeline
terms this is your handler logic; the game loop is just the runtime around it.
"""

from __future__ import annotations

from .arsenal import GUN_LIBRARY, MODULE_LIBRARY, Gun, Turret, gun_cost, make_gun
from .economy import Bank

# A click within this many pixels of a turret's center selects that turret.
PICK_RADIUS = 14.0


class ArsenalEditor:
    """Mutable working set of turrets plus the current "what to place" choice.

    Typical flow:
        ed = ArsenalEditor(world.unlocked())
        ed.seed(build_loadout(...))   # start from the file-based loadout
        ed.select_gun("sieve")        # pick from the palette
        ed.toggle_module("range+")    # queue an upgrade onto it
        ed.place(x, y)                # drop it where the user clicked
        world.set_turrets(ed.to_turrets())
    """

    def __init__(self, unlocked: set[str] | None = None, bank: Bank | None = None) -> None:
        self.turrets: list[Turret] = []
        self.selected_gun: str | None = None
        self.pending_modules: list[str] = []
        # copy the set so later edits here don't mutate the caller's set
        self.unlocked: set[str] = set(unlocked or set())
        # Shared with the World by reference; None means "no economy" (free mode).
        self.bank: Bank | None = bank

    # ---- palette: what the player may choose, gated by unlocks ---- #
    def available_guns(self) -> list[str]:
        """Registered gun names the player has unlocked (drives the palette)."""
        return sorted(n for n in GUN_LIBRARY if n in self.unlocked)

    def available_modules(self) -> list[str]:
        """Registered module names the player has unlocked."""
        return sorted(n for n in MODULE_LIBRARY if n in self.unlocked)

    def set_unlocked(self, unlocked: set[str]) -> None:
        """Refresh unlocks (waves advance) and drop now-invalid selections."""
        self.unlocked = set(unlocked)
        if self.selected_gun is not None and self.selected_gun not in self.available_guns():
            self.selected_gun = None
        self.pending_modules = [m for m in self.pending_modules if m in self.available_modules()]

    # ---- seeding from / exporting to the simulation ---- #
    def seed(self, turrets: list[Turret]) -> None:
        """Load an existing loadout so the player edits from it rather than blank.

        ``list(turrets)`` makes our own list; we never mutate the caller's.
        """
        self.turrets = list(turrets)

    def to_turrets(self) -> list[Turret]:
        """The turrets to hand to ``World.set_turrets`` (a fresh list)."""
        return list(self.turrets)

    def clear(self) -> None:
        self.turrets = []

    # ---- choosing what to place ---- #
    def select_gun(self, name: str) -> bool:
        """Pick the gun to place next. Returns False if it isn't available."""
        if name not in self.available_guns():
            return False
        self.selected_gun = name
        self.pending_modules = []  # module choices are per-gun; start fresh
        return True

    def toggle_module(self, name: str) -> bool:
        """Queue/unqueue a module onto the gun-to-place. False if unavailable."""
        if name not in self.available_modules():
            return False
        if name in self.pending_modules:
            self.pending_modules.remove(name)
        else:
            self.pending_modules.append(name)
        return True

    def _build_gun(self) -> Gun | None:
        """Build the currently selected gun with its queued modules attached.

        ``Gun | None`` says "a Gun, or nothing if no gun is selected" — callers
        must handle the None case, and mypy enforces it.
        """
        if self.selected_gun is None:
            return None
        gun = make_gun(self.selected_gun)
        for m in self.pending_modules:
            gun.attach(MODULE_LIBRARY[m])
        return gun

    # ---- placing / picking / removing on the map ---- #
    def pending_cost(self) -> int:
        """Credit cost of the current selection (gun + queued modules); 0 if none.

        The UI uses this to show a price tag and grey out unaffordable choices.
        """
        gun = self._build_gun()
        return gun_cost(gun) if gun is not None else 0

    def place(self, x: float, y: float) -> Turret | None:
        """Drop a turret with the selected gun at (x, y).

        Returns None if no gun is selected, or if a bank is attached and the
        balance can't cover the cost (nothing is charged in that case).
        """
        gun = self._build_gun()
        if gun is None:
            return None
        if self.bank is not None and not self.bank.spend(gun_cost(gun)):
            return None
        turret = Turret(x, y, gun=gun)
        self.turrets.append(turret)
        return turret

    def turret_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> Turret | None:
        """The closest turret within ``radius`` of (x, y), or None.

        ``min(..., key=...)`` returns the item with the smallest key value; the
        ``key`` function maps each turret to its squared distance from the click,
        so we get the nearest one. (Squared distance avoids a needless sqrt.)
        """
        in_range = [
            t for t in self.turrets if (t.x - x) ** 2 + (t.y - y) ** 2 <= radius * radius
        ]
        if not in_range:
            return None
        return min(in_range, key=lambda t: (t.x - x) ** 2 + (t.y - y) ** 2)

    def remove_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> bool:
        """Remove the turret under the click, refunding its cost. True if removed.

        Full refund means the budget constrains *peak* deployment, not churn —
        you can freely rearrange, but everything live at once must fit.
        """
        target = self.turret_at(x, y, radius)
        if target is None:
            return False
        self.turrets.remove(target)
        if self.bank is not None:
            self.bank.earn(gun_cost(target.gun))
        return True

    def equip_at(self, x: float, y: float, module: str, radius: float = PICK_RADIUS) -> bool:
        """Attach a module to the turret under the click.

        Refuses if the module isn't unlocked, no turret is under the cursor, or
        that turret's gun already has the module (no silent double-stacking).
        """
        if module not in self.available_modules():
            return False
        target = self.turret_at(x, y, radius)
        if target is None:
            return False
        if any(m.name == module for m in target.gun.modules):
            return False
        mod = MODULE_LIBRARY[module]
        if self.bank is not None and not self.bank.spend(mod.cost):
            return False
        target.gun.attach(mod)
        return True
