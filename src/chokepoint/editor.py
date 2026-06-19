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
from .gates import DEFAULT_GATE_COST, Gate
from .limiter import DEFAULT_LIMITER_COST, Limiter

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
        self.gates: list[Gate] = []
        self.limiters: list[Limiter] = []
        self.selected_gun: str | None = None
        self.pending_modules: list[str] = []
        self.placing_gate = False     # True = the next playfield click drops a gate
        self.placing_limiter = False  # True = the next playfield click drops a limiter
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

        ``list(turrets)`` makes our own list; we never mutate the caller's. This
        does NOT charge the bank — use ``seed_purchase`` when the budget applies.
        """
        self.turrets = list(turrets)

    def seed_purchase(self, turrets: list[Turret]) -> list[Turret]:
        """Load turrets, paying for each from the bank in order.

        Turrets that don't fit the remaining budget are skipped and returned, so
        a too-expensive loadout deploys what it can afford and the UI can report
        the rest. With no bank attached, everything is kept (free mode).
        """
        self.turrets = []
        dropped: list[Turret] = []
        for t in turrets:
            if self.bank is None or self.bank.spend(gun_cost(t.gun)):
                self.turrets.append(t)
            else:
                dropped.append(t)
        return dropped

    def to_turrets(self) -> list[Turret]:
        """The turrets to hand to ``World.set_turrets`` (a fresh list)."""
        return list(self.turrets)

    def to_python(self) -> str:
        """Generate a loadout.py source string from the current placement.

        This is code generation: we emit the same ``build_loadout`` the player
        would hand-write, with each turret's gun, modules, and position baked in.
        Saving it (press S in-game) lets a player keep a build and resume later —
        the game loads loadout.py on launch and F5 reloads it. The ``unlocked``/
        ``slots`` params are kept for signature compatibility but unused here,
        since positions are fixed.
        """
        # only import what this build actually uses (keeps the file lint-clean)
        uses_modules = any(t.gun.modules for t in self.turrets)
        arsenal_names = "MODULE_LIBRARY, Turret, make_gun" if uses_modules else "Turret, make_gun"
        lines = [
            '"""Exported loadout — generated by the in-game editor (press S).',
            "",
            "Drop-in build_loadout (+ build_gates): relaunch or press F5 to load it.",
            '"""',
            "from __future__ import annotations",
            "",
            f"from {__package__}.arsenal import {arsenal_names}",
        ]
        if self.gates:
            lines.append(f"from {__package__}.gates import Gate")
        if self.limiters:
            lines.append(f"from {__package__}.limiter import Limiter")
        lines += ["", "", "def build_loadout(unlocked, slots):", "    turrets = []"]
        for i, t in enumerate(self.turrets):
            g = f"g{i}"
            lines.append(f'    {g} = make_gun("{t.gun.name}")')
            for m in t.gun.modules:
                lines.append(f'    {g}.attach(MODULE_LIBRARY["{m.name}"])')
            lines.append(f"    turrets.append(Turret({t.x!r}, {t.y!r}, gun={g}))")
        lines.append("    return turrets")
        lines += ["", ""]
        # gates persist by position only; the World re-derives their routing
        lines.append("def build_gates(unlocked, slots):")
        if self.gates:
            lines.append("    return [")
            lines += [f"        Gate({gt.x!r}, {gt.y!r})," for gt in self.gates]
            lines.append("    ]")
        else:
            lines.append("    return []")
        lines += ["", ""]
        # limiters persist by position; release rate / buffer use their defaults
        lines.append("def build_limiters(unlocked, slots):")
        if self.limiters:
            lines.append("    return [")
            lines += [f"        Limiter({lm.x!r}, {lm.y!r})," for lm in self.limiters]
            lines.append("    ]")
        else:
            lines.append("    return []")
        lines.append("")
        return "\n".join(lines)

    def clear(self) -> None:
        self.turrets = []
        self.gates = []
        self.limiters = []

    # ---- choosing what to place ---- #
    def select_gun(self, name: str) -> bool:
        """Pick the gun to place next. Returns False if it isn't available."""
        if name not in self.available_guns():
            return False
        self.selected_gun = name
        self.pending_modules = []  # module choices are per-gun; start fresh
        self.placing_gate = self.placing_limiter = False  # leave device-placement modes
        return True

    def select_gate(self) -> bool:
        """Switch to gate-placement mode (the next playfield click drops a gate)."""
        self.placing_gate = True
        self.placing_limiter = False
        return True

    def select_limiter(self) -> bool:
        """Switch to quelimiter-placement mode."""
        self.placing_limiter = True
        self.placing_gate = False
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
        """Credit cost of the current selection; gate cost in gate mode, else the
        gun + queued modules (0 if nothing selected). Drives price tags / affordability.
        """
        if self.placing_limiter:
            return DEFAULT_LIMITER_COST
        if self.placing_gate:
            return DEFAULT_GATE_COST
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

    # ---- gates (placed by click; routing is auto-derived by the World) ---- #
    def to_gates(self) -> list[Gate]:
        return list(self.gates)

    def place_gate(self, x: float, y: float) -> Gate | None:
        """Drop a gate at (x, y). None if a bank can't cover the cost."""
        if self.bank is not None and not self.bank.spend(DEFAULT_GATE_COST):
            return None
        gate = Gate(x, y)
        self.gates.append(gate)
        return gate

    def gate_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> Gate | None:
        in_range = [g for g in self.gates if (g.x - x) ** 2 + (g.y - y) ** 2 <= radius * radius]
        if not in_range:
            return None
        return min(in_range, key=lambda g: (g.x - x) ** 2 + (g.y - y) ** 2)

    def remove_gate_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> bool:
        """Remove the gate under the click, refunding its cost. True if removed."""
        target = self.gate_at(x, y, radius)
        if target is None:
            return False
        self.gates.remove(target)
        if self.bank is not None:
            self.bank.earn(target.cost)
        return True

    def seed_purchase_gates(self, gates: list[Gate]) -> list[Gate]:
        """Load saved gates, paying for each (mirrors seed_purchase for turrets)."""
        self.gates = []
        dropped: list[Gate] = []
        for g in gates:
            if self.bank is None or self.bank.spend(g.cost):
                self.gates.append(g)
            else:
                dropped.append(g)
        return dropped

    # ---- quelimiters (placed by click on any node) ---- #
    def to_limiters(self) -> list[Limiter]:
        return list(self.limiters)

    def place_limiter(self, x: float, y: float) -> Limiter | None:
        """Drop a quelimiter at (x, y). None if a bank can't cover the cost."""
        if self.bank is not None and not self.bank.spend(DEFAULT_LIMITER_COST):
            return None
        lim = Limiter(x, y)
        self.limiters.append(lim)
        return lim

    def limiter_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> Limiter | None:
        in_range = [m for m in self.limiters
                    if (m.x - x) ** 2 + (m.y - y) ** 2 <= radius * radius]
        if not in_range:
            return None
        return min(in_range, key=lambda m: (m.x - x) ** 2 + (m.y - y) ** 2)

    def remove_limiter_at(self, x: float, y: float, radius: float = PICK_RADIUS) -> bool:
        """Remove the limiter under the click, refunding its cost. True if removed."""
        target = self.limiter_at(x, y, radius)
        if target is None:
            return False
        self.limiters.remove(target)
        if self.bank is not None:
            self.bank.earn(target.cost)
        return True

    def seed_purchase_limiters(self, limiters: list[Limiter]) -> list[Limiter]:
        """Load saved limiters, paying for each (mirrors seed_purchase for turrets)."""
        self.limiters = []
        dropped: list[Limiter] = []
        for lim in limiters:
            if self.bank is None or self.bank.spend(lim.cost):
                self.limiters.append(lim)
            else:
                dropped.append(lim)
        return dropped
