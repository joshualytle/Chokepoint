"""Pygame renderer + tooltips + map switching + loadout hot-reload + LLM helper.

Run: ``python -m factory_defense``. Logic lives in the other modules; this only
draws state and handles input.

Controls:
  [ / ]   previous / next map        R   reset
  P       pause / resume             F5  reload your loadout.py
  L       ask your local LLM for help (optional; off-thread, never freezes)
  hover   a turret or a legend swatch for a tooltip
"""

from __future__ import annotations

import importlib
import threading

from . import llm_assist
from . import loadout as loadout_mod
from .maps import GW, MAP_LIST, MAPS
from .packets import KINDS
from .simulation import MAX_LEAK, World


def main() -> None:  # pragma: no cover - needs a display
    import pygame

    pygame.init()
    pygame.key.set_repeat(250, 30)
    WIN_W, WIN_H = 1100, 680
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Packet Defense — typed turrets vs an alert flood")
    clock = pygame.time.Clock()

    def font(sz: int, bold: bool = False):
        return pygame.font.SysFont("menlo,consolas,dejavusansmono,monospace", sz, bold=bold)

    F_S, F_M, F_L = font(13), font(15), font(20, True)

    BG = (14, 22, 34)
    PANEL = (19, 31, 46)
    PANEL2 = (11, 19, 32)
    GRID = (28, 44, 62)
    INK = (199, 213, 224)
    MUTED = (94, 116, 136)
    PHOS = (56, 225, 176)
    DANGER = (229, 85, 110)

    map_i = 0
    world = World(MAPS[MAP_LIST[map_i]])
    fire_beams: list[tuple[float, float, float, float, float]] = []  # x1,y1,x2,y2,ttl
    llm_state: dict[str, str] = {"status": "idle", "text": "Press L for local-LLM help."}

    def rebuild_loadout() -> None:
        gm = world.map
        turrets = loadout_mod.build_loadout(world.unlocked(), gm.slots)
        world.set_turrets(turrets)

    def switch_map(delta: int) -> None:
        nonlocal map_i, world
        map_i = (map_i + delta) % len(MAP_LIST)
        world = World(MAPS[MAP_LIST[map_i]])
        rebuild_loadout()

    def ask_llm() -> None:
        llm_state["status"] = "thinking"
        llm_state["text"] = "Asking your local LLM..."

        def work() -> None:
            ctx = llm_assist.state_summary(world)
            llm_state["text"] = llm_assist.diagnose(
                ctx, "What is leaking and how should I change my loadout to fix it?"
            )
            llm_state["status"] = "done"

        threading.Thread(target=work, daemon=True).start()

    def wrap(text: str, width: int, f) -> list[str]:
        out: list[str] = []
        for para in text.splitlines():
            line = ""
            for word in para.split(" "):
                trial = f"{line} {word}".strip()
                if f.size(trial)[0] > width and line:
                    out.append(line)
                    line = word
                else:
                    line = trial
            out.append(line)
        return out

    rebuild_loadout()

    def text(s: str, x: int, y: int, f=F_S, c=INK) -> None:
        screen.blit(f.render(s, True, c), (x, y))

    PANEL_X = GW + 10
    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        mouse = pygame.mouse.get_pos()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_LEFTBRACKET:
                    switch_map(-1)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    switch_map(1)
                elif ev.key == pygame.K_r:
                    world.reset()
                    rebuild_loadout()
                elif ev.key == pygame.K_p:
                    world.paused = not world.paused
                elif ev.key == pygame.K_F5:
                    importlib.reload(loadout_mod)
                    rebuild_loadout()
                    llm_state["text"] = "Loadout reloaded."
                elif ev.key == pygame.K_l:
                    ask_llm()

        if not world.paused and not world.over:
            acc = dt
            while acc > 0:
                world.step(min(1 / 60, acc))
                acc -= 1 / 60

        # ---- draw playfield ----
        screen.fill(BG)
        for x in range(0, GW, 40):
            pygame.draw.line(screen, GRID, (x, 0), (x, WIN_H))
        for y in range(0, WIN_H, 40):
            pygame.draw.line(screen, GRID, (0, y), (GW, y))
        pygame.draw.lines(screen, (42, 66, 89), False, world.map.path, 16)
        ex = world.map.path[-1]
        pygame.draw.rect(screen, DANGER, (ex[0] - 14, ex[1] - 20, 7, 40))

        hovered_turret = None
        for t in world.turrets:
            surf = pygame.Surface((t.range() * 2, t.range() * 2), pygame.SRCALPHA)
            pygame.draw.circle(surf, (56, 225, 176, 12), (t.range(), t.range()), t.range())
            pygame.draw.circle(surf, (56, 225, 176, 45), (t.range(), t.range()), t.range(), 1)
            screen.blit(surf, (t.x - t.range(), t.y - t.range()))
            pygame.draw.circle(screen, BG, (int(t.x), int(t.y)), 12)
            pygame.draw.circle(screen, PHOS, (int(t.x), int(t.y)), 12, 2)
            text(t.id, int(t.x) - 8, int(t.y) - 30, F_S, PHOS)
            # accepted-kind swatches under the turret
            for i, k in enumerate(sorted(t.accepts())):
                pygame.draw.rect(screen, KINDS[k]["color"], (t.x - 14 + i * 6, t.y + 14, 5, 5))
            if (mouse[0] - t.x) ** 2 + (mouse[1] - t.y) ** 2 <= 16 * 16:
                hovered_turret = t

        for p in world.packets:
            px, py = world.map.pos_at(p.d)
            r = max(3, int(7 * p.volume / p.maxvol))
            pygame.draw.circle(screen, KINDS[p.kind]["color"], (int(px), int(py)), r)

        for beam in fire_beams:
            pygame.draw.line(screen, (234, 247, 241), (beam[0], beam[1]), (beam[2], beam[3]), 1)
        fire_beams = [(*b[:4], b[4] - dt) for b in fire_beams if b[4] - dt > 0]

        if world.intermission > 0 and not world.over:
            text(f"Wave {world.level} incoming...", GW // 2 - 70, 14, F_M, INK)
        text(f"map: {world.map.name}   [ ] to switch", 12, WIN_H - 22, F_S, MUTED)

        # ---- panel ----
        text("PACKET DEFENSE", PANEL_X, 16, F_M, PHOS)
        text(f"wave {world.level}", PANEL_X, 40, F_S, INK)
        leak_c = DANGER if world.leaks >= MAX_LEAK - 3 else INK
        text(f"leaks {world.leaks}/{MAX_LEAK}", PANEL_X + 110, 40, F_S, leak_c)

        gaps = sorted(world.coverage_gaps())
        if gaps:
            text("COVERAGE GAP: " + ", ".join(gaps), PANEL_X, 60, F_S, DANGER)
        else:
            text("coverage: all seen kinds handled", PANEL_X, 60, F_S, PHOS)

        # per-kind table
        text("KIND        in  ok  leak  now", PANEL_X, 86, F_S, MUTED)
        row = 104
        for k, s in world.stats.items():
            if s.spawned == 0:
                continue
            pygame.draw.rect(screen, KINDS[k]["color"], (PANEL_X, row + 2, 8, 8))
            line = f"{k:<10} {s.spawned:>3} {s.handled:>3} {s.leaked:>4} {s.inflight:>4}"
            text(line, PANEL_X + 14, row, F_S, INK if s.leaked == 0 else DANGER)
            row += 18

        row += 8
        text("UNLOCKED: " + ", ".join(sorted(world.unlocked())), PANEL_X, row, F_S, MUTED)
        row += 26

        # LLM helper area
        pygame.draw.rect(screen, PANEL, (PANEL_X, row, WIN_W - PANEL_X - 14, 150), border_radius=6)
        text("LOCAL LLM HELP  (press L)", PANEL_X + 10, row + 8, F_S, MUTED)
        for i, ln in enumerate(wrap(llm_state["text"], WIN_W - PANEL_X - 40, F_S)[:7]):
            text(ln, PANEL_X + 10, row + 28 + i * 16, F_S, INK)

        # tooltip on top of everything
        if hovered_turret is not None:
            g = hovered_turret.gun
            lines = [
                f"{hovered_turret.id}: {g.name}",
                g.desc,
                f"accepts: {', '.join(sorted(hovered_turret.accepts()))}",
                f"fire rate {g.fire_rate}/s (static)   range {hovered_turret.range():.0f}",
                f"dps {hovered_turret.dps():.1f}"
                + (f"   x{hovered_turret.synergy_mult:.2f} synergy"
                   if hovered_turret.synergy_mult > 1 else ""),
            ]
            if g.modules:
                lines.append("modules: " + ", ".join(m.name for m in g.modules))
            w = max(F_S.size(s)[0] for s in lines) + 16
            h = len(lines) * 16 + 10
            bx, by = min(mouse[0] + 12, GW - w), mouse[1] + 12
            pygame.draw.rect(screen, PANEL2, (bx, by, w, h), border_radius=5)
            pygame.draw.rect(screen, PHOS, (bx, by, w, h), 1, border_radius=5)
            for i, ln in enumerate(lines):
                text(ln, bx + 8, by + 6 + i * 16, F_S, INK if i else PHOS)

        if world.over:
            ov = pygame.Surface((GW, WIN_H), pygame.SRCALPHA)
            ov.fill((8, 14, 22, 210))
            screen.blit(ov, (0, 0))
            msg = "PIPELINE HELD" if world.won else "PIPELINE OVERWHELMED"
            text(msg, GW // 2 - 110, WIN_H // 2 - 30, F_L, PHOS if world.won else DANGER)
            text("Press R to retry, or edit loadout.py and F5.",
                 GW // 2 - 150, WIN_H // 2 + 4, F_S, INK)

        pygame.display.flip()

    pygame.quit()
