"""Pygame renderer + tooltips + map switching + loadout hot-reload + LLM helper.

Run: ``python -m chokepoint``. Logic lives in the other modules; this only
draws state and handles input.

Controls:
  [ / ]   previous / next map        R   reset
  P       pause / resume             F5  reload your loadout.py
  E       toggle the placement editor (buy/place/equip/remove turrets)
  M       toggle the metrics dashboard (queues, by-kind, health trend)
  S       save the current build to loadout.py (resume it next launch / F5)
  D       cycle difficulty (easy / adaptive / overkill) — resets the run
  L       ask your local LLM for help (optional; off-thread, never freezes)
  hover   a turret or a legend swatch for a tooltip

Editor (press E): click a gun in the palette (or 1-9) to select it, click a
module row to queue it, then left-click the map to place. Left-click an existing
turret to equip your queued modules onto it; right-click to remove (full refund).
Pick the gate router (click it or press G) and left-click near a fork to place a
gate; it auto-routes each kind to the branch whose consumers can handle it.
Everything is charged against your credits, which grow as you clear waves.
"""

from __future__ import annotations

import importlib
import threading
from typing import Any

from . import llm_assist
from . import loadout as loadout_mod
from .arsenal import MODULE_LIBRARY, gun_cost, make_gun
from .editor import ArsenalEditor
from .gates import DEFAULT_GATE_COST
from .maps import GW, MAP_LIST, MAPS
from .metrics import summarize_failure
from .packets import DIFFICULTY_LIST, KINDS
from .simulation import MAX_LEAK, QUEUE_CAP, START_HEALTH, World

QUEUE_WARN = QUEUE_CAP - 2  # queue depth at which a node's marker turns red


def main() -> None:  # pragma: no cover - needs a display
    import pygame

    pygame.init()
    pygame.key.set_repeat(250, 30)
    WIN_W, WIN_H = 1100, 680
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Chokepoint — typed turrets vs an alert flood")
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
    GATE_C = (240, 200, 120)

    map_i = 0
    difficulty_i = 0
    world = World(MAPS[MAP_LIST[map_i]], difficulty=DIFFICULTY_LIST[difficulty_i])
    editor = ArsenalEditor(world.unlocked(), bank=world.bank)
    edit_mode = False
    metrics_mode = False
    # palette rows registered each frame so panel clicks can be mapped to actions:
    # (rect, "gun"|"mod", name)
    palette_hits: list[tuple[Any, str, str]] = []
    llm_state: dict[str, str] = {"status": "idle", "text": "Press L for local-LLM help."}

    def deploy_loadout(refund_current: bool = False) -> None:
        """(Re)build turrets from loadout.py, costed against the budget.

        The editor is the single source of truth; loadout.py is its initial paid
        build. ``refund_current`` (used by F5) returns the cost of whatever is
        deployed before re-buying, so reloading the file never double-charges.
        """
        nonlocal editor
        if refund_current:
            for t in world.turrets:
                world.bank.earn(gun_cost(t.gun))
            for gt in world.gates:
                world.bank.earn(gt.cost)
        editor = ArsenalEditor(world.unlocked(), bank=world.bank)
        dropped = editor.seed_purchase(
            loadout_mod.build_loadout(world.unlocked(), world.map.slots)
        )
        # gates are optional in a saved loadout (older files have no build_gates)
        build_gates = getattr(loadout_mod, "build_gates", None)
        if build_gates is not None:
            editor.seed_purchase_gates(build_gates(world.unlocked(), world.map.slots))
        sync_world()
        if dropped:
            llm_state["text"] = (
                f"Over budget: {len(dropped)} loadout turret(s) not deployed."
            )

    def sync_world() -> None:
        """Push the editor's turrets + gates to the world and re-derive routing."""
        world.set_turrets(editor.to_turrets())
        world.set_gates(editor.to_gates())
        world.autoroute()

    def switch_map(delta: int) -> None:
        nonlocal map_i, world, edit_mode
        map_i = (map_i + delta) % len(MAP_LIST)
        world = World(MAPS[MAP_LIST[map_i]], difficulty=DIFFICULTY_LIST[difficulty_i])
        edit_mode = False
        deploy_loadout()

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

    deploy_loadout()

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
                    deploy_loadout()
                elif ev.key == pygame.K_p:
                    world.paused = not world.paused
                elif ev.key == pygame.K_F5:
                    importlib.reload(loadout_mod)
                    deploy_loadout(refund_current=True)
                    llm_state["text"] = "Loadout reloaded."
                elif ev.key == pygame.K_e:
                    edit_mode = not edit_mode
                elif ev.key == pygame.K_m:
                    metrics_mode = not metrics_mode
                elif ev.key == pygame.K_s:
                    # save the current build to loadout.py so it loads next launch
                    try:
                        with open(loadout_mod.__file__, "w", encoding="utf-8") as fh:
                            fh.write(editor.to_python())
                        llm_state["text"] = f"Saved loadout to {loadout_mod.__file__}"
                    except OSError as err:
                        llm_state["text"] = f"Save failed: {err}"
                elif ev.key == pygame.K_d:
                    difficulty_i = (difficulty_i + 1) % len(DIFFICULTY_LIST)
                    world.difficulty = DIFFICULTY_LIST[difficulty_i]
                    world.reset()
                    deploy_loadout()
                elif ev.key == pygame.K_l:
                    ask_llm()
                elif edit_mode and ev.key == pygame.K_g:
                    editor.select_gate()  # gate-placement mode
                elif edit_mode and pygame.K_1 <= ev.key <= pygame.K_9:
                    guns = editor.available_guns()
                    idx = ev.key - pygame.K_1
                    if idx < len(guns):
                        editor.select_gun(guns[idx])
            elif ev.type == pygame.MOUSEBUTTONDOWN and edit_mode:
                mx, my = ev.pos
                if mx < GW:  # click on the playfield -> place / equip / remove
                    if ev.button == 1:
                        if editor.placing_gate:
                            editor.place_gate(mx, my)
                        else:
                            hit = editor.turret_at(mx, my)
                            if hit is not None and editor.pending_modules:
                                for m in list(editor.pending_modules):
                                    editor.equip_at(mx, my, m)
                            else:
                                editor.place(mx, my)
                        sync_world()
                    elif ev.button == 3:  # remove a turret, or a gate if none there
                        if editor.remove_at(mx, my) or editor.remove_gate_at(mx, my):
                            sync_world()
                elif ev.button == 1:  # click on the panel -> palette selection
                    for rect, kind, name in palette_hits:
                        if rect.collidepoint(mx, my):
                            if kind == "gun":
                                editor.select_gun(name)
                            elif kind == "gate":
                                editor.select_gate()
                            else:
                                editor.toggle_module(name)
                            break

        # keep the editor palette in step with what the current wave has unlocked
        editor.set_unlocked(world.unlocked())

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
        # ---- topology: edges, then nodes with their queues ----
        for src, dst in world.map.edges():
            pygame.draw.line(screen, (42, 66, 89), world.map.pos(src), world.map.pos(dst), 12)
        for nid, node in world.map.nodes.items():
            q = world.queue_at(nid)
            nx, ny = int(node.x), int(node.y)
            if nid == world.map.sink:
                pygame.draw.rect(screen, DANGER, (nx - 8, ny - 20, 7, 40))
            depth_c = DANGER if len(q) > QUEUE_WARN else MUTED
            pygame.draw.circle(screen, depth_c, (nx, ny), 5)
            if q:
                text(str(len(q)), nx + 7, ny - 7, F_S, depth_c)
            # queued packets stacked beside the node (size shrinks as volume drains)
            for j, p in enumerate(q):
                r = max(3, int(6 * p.volume / p.maxvol))
                pygame.draw.circle(screen, KINDS[p.kind]["color"],
                                   (nx + 12 + (j % 4) * 8, ny - 12 + (j // 4) * 8), r)

        hovered_turret = None
        for t in world.turrets:
            if t.node in world.map.nodes:  # tether the turret to the queue it serves
                pygame.draw.line(screen, GRID, (int(t.x), int(t.y)), world.map.pos(t.node), 1)
            pygame.draw.circle(screen, BG, (int(t.x), int(t.y)), 12)
            pygame.draw.circle(screen, PHOS, (int(t.x), int(t.y)), 12, 2)
            text(t.id, int(t.x) - 8, int(t.y) - 30, F_S, PHOS)
            for i, k in enumerate(sorted(t.accepts())):
                pygame.draw.rect(screen, KINDS[k]["color"], (t.x - 14 + i * 6, t.y + 14, 5, 5))
            if (mouse[0] - t.x) ** 2 + (mouse[1] - t.y) ** 2 <= 16 * 16:
                hovered_turret = t

        # gates: a diamond at the fork, with the kinds routed down each branch
        for gt in world.gates:
            if gt.node not in world.map.nodes:
                continue
            gx, gy = (int(v) for v in world.map.pos(gt.node))
            diamond = [(gx, gy - 13), (gx + 13, gy), (gx, gy + 13), (gx - 13, gy)]
            pygame.draw.polygon(screen, BG, diamond)
            pygame.draw.polygon(screen, GATE_C, diamond, 2)
            text(gt.id, gx - 8, gy - 32, F_S, GATE_C)
            for bi, bnode in enumerate(world.map.branches(gt.node)):
                bx, by = world.map.pos(bnode)
                tx, ty = gx + (bx - gx) * 0.28, gy + (by - gy) * 0.28
                routed = [k for k, idx in gt.routes.items() if idx == bi]
                for ci, k in enumerate(routed):
                    pygame.draw.rect(screen, KINDS[k]["color"], (tx - 6 + ci * 6, ty - 2, 5, 5))

        # placement preview: highlight what a click would bind to
        if edit_mode and mouse[0] < GW and editor.placing_gate:
            col = PHOS if world.bank.can_afford(editor.pending_cost()) else DANGER
            fork = world.map.nearest_branch_node(mouse[0], mouse[1])
            if fork is not None:
                fx, fy = (int(v) for v in world.map.pos(fork))
                pygame.draw.line(screen, col, mouse, (fx, fy), 1)
                pygame.draw.polygon(screen, col,
                                    [(fx, fy - 15), (fx + 15, fy), (fx, fy + 15), (fx - 15, fy)], 2)
            else:
                text("no fork on this map", mouse[0] + 12, mouse[1], F_S, DANGER)
        elif edit_mode and mouse[0] < GW and editor.selected_gun is not None:
            col = PHOS if world.bank.can_afford(editor.pending_cost()) else DANGER
            nid = world.map.nearest_node(mouse[0], mouse[1])
            pygame.draw.line(screen, col, mouse, world.map.pos(nid), 1)
            pygame.draw.circle(screen, col, world.map.pos(nid), 15, 2)
            pygame.draw.circle(screen, col, mouse, 10, 2)

        # in-transit packets, interpolated along their edge
        for p in world.packets:
            if p.moving_to is None:
                continue
            ax, ay = world.map.pos(p.at)
            bx, by = world.map.pos(p.moving_to)
            f = min(1.0, p.seg_pos / (world.map.edge_len(p.at, p.moving_to) or 1.0))
            r = max(3, int(7 * p.volume / p.maxvol))
            pygame.draw.circle(screen, KINDS[p.kind]["color"],
                               (int(ax + (bx - ax) * f), int(ay + (by - ay) * f)), r)

        if world.intermission > 0 and not world.over:
            text(f"Wave {world.level} incoming...", GW // 2 - 70, 14, F_M, INK)
        text(f"map: {world.map.name}   [ ] to switch", 12, WIN_H - 22, F_S, MUTED)
        text(f"mode: {world.difficulty}   D to cycle", 12, WIN_H - 40, F_S, MUTED)

        # ---- panel ----
        text("CHOKEPOINT", PANEL_X, 16, F_M, PHOS)
        text(f"wave {world.level}", PANEL_X, 40, F_S, INK)
        leak_c = DANGER if world.leaks >= MAX_LEAK - 3 else INK
        text(f"leaks {world.leaks}/{MAX_LEAK}", PANEL_X + 110, 40, F_S, leak_c)
        text(f"cr {world.bank.balance}", PANEL_X + 240, 40, F_S, PHOS)

        # health: the latency budget, bled by packets that sit queued too long
        hp_frac = max(0.0, world.health / START_HEALTH)
        hp_c = DANGER if hp_frac < 0.34 else (INK if hp_frac < 0.67 else PHOS)
        text(f"health {world.health:.0f}", PANEL_X, 60, F_S, hp_c)
        pygame.draw.rect(screen, GRID, (PANEL_X + 90, 62, 120, 8))
        pygame.draw.rect(screen, hp_c, (PANEL_X + 90, 62, int(120 * hp_frac), 8))

        gaps = sorted(world.coverage_gaps())
        if gaps:
            text("COVERAGE GAP: " + ", ".join(gaps), PANEL_X, 78, F_S, DANGER)
        else:
            text("coverage: all seen kinds handled", PANEL_X, 78, F_S, PHOS)

        # per-kind table
        text("KIND        in  ok  leak  now", PANEL_X, 100, F_S, MUTED)
        row = 118
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

        panel_w = WIN_W - PANEL_X - 14
        palette_hits.clear()
        if edit_mode:
            text("EDIT MODE — E to exit", PANEL_X, row, F_S, PHOS)
            row += 18
            text("LMB place · LMB on turret = equip · RMB remove", PANEL_X, row, F_S, MUTED)
            row += 20
            text("GUNS  (click or 1-9)", PANEL_X, row, F_S, MUTED)
            row += 17
            for i, name in enumerate(editor.available_guns()):
                g = make_gun(name)
                sel = name == editor.selected_gun
                color = PHOS if sel else (INK if world.bank.can_afford(g.cost) else MUTED)
                palette_hits.append((pygame.Rect(PANEL_X, row - 1, panel_w, 17), "gun", name))
                text(f"{i + 1} {name:<8}{g.cost:>4}cr  {','.join(sorted(g.accepts))}",
                     PANEL_X + 2, row, F_S, color)
                row += 17
            row += 6
            text("MODULES  (click to queue)", PANEL_X, row, F_S, MUTED)
            row += 17
            for name in editor.available_modules():
                mod = MODULE_LIBRARY[name]
                queued = name in editor.pending_modules
                color = PHOS if queued else (INK if world.bank.can_afford(mod.cost) else MUTED)
                palette_hits.append((pygame.Rect(PANEL_X, row - 1, panel_w, 17), "mod", name))
                text(f"[{'x' if queued else ' '}] {name:<15}{mod.cost:>3}cr",
                     PANEL_X + 2, row, F_S, color)
                row += 17
            row += 6
            text("ROUTERS  (click or G)", PANEL_X, row, F_S, MUTED)
            row += 17
            gcolor = GATE_C if editor.placing_gate else (
                INK if world.bank.can_afford(DEFAULT_GATE_COST) else MUTED)
            palette_hits.append((pygame.Rect(PANEL_X, row - 1, panel_w, 17), "gate", "gate"))
            text(f"gate {DEFAULT_GATE_COST:>4}cr  (routes kinds at a fork)",
                 PANEL_X + 2, row, F_S, gcolor)
            row += 21
            if editor.placing_gate:
                color = PHOS if world.bank.can_afford(DEFAULT_GATE_COST) else DANGER
                text(f"to place: gate  {DEFAULT_GATE_COST}cr", PANEL_X, row, F_S, color)
            elif editor.selected_gun is not None:
                sc = editor.pending_cost()
                color = PHOS if world.bank.can_afford(sc) else DANGER
                text(f"to place: {editor.selected_gun}  {sc}cr", PANEL_X, row, F_S, color)
        else:
            # LLM helper area
            pygame.draw.rect(screen, PANEL, (PANEL_X, row, panel_w, 150), border_radius=6)
            text("LOCAL LLM HELP  (press L)", PANEL_X + 10, row + 8, F_S, MUTED)
            for i, ln in enumerate(wrap(llm_state["text"], panel_w - 26, F_S)[:7]):
                text(ln, PANEL_X + 10, row + 28 + i * 16, F_S, INK)

        # tooltip on top of everything
        if hovered_turret is not None:
            g = hovered_turret.gun
            lines = [
                f"{hovered_turret.id}: {g.name}",
                g.desc,
                f"accepts: {', '.join(sorted(hovered_turret.accepts()))}",
                f"fire rate {g.fire_rate}/s (static)   "
                f"node {hovered_turret.node} (q{len(world.queue_at(hovered_turret.node))})",
                f"dps {hovered_turret.dps():.1f}"
                + (f"   x{hovered_turret.synergy_mult:.2f} synergy"
                   if hovered_turret.synergy_mult > 1 else ""),
            ]
            if g.modules:
                lines.append("modules: " + ", ".join(m.name for m in g.modules))
            lines.append(f"cost {gun_cost(g)}cr")
            w = max(F_S.size(s)[0] for s in lines) + 16
            h = len(lines) * 16 + 10
            bx, by = min(mouse[0] + 12, GW - w), mouse[1] + 12
            pygame.draw.rect(screen, PANEL2, (bx, by, w, h), border_radius=5)
            pygame.draw.rect(screen, PHOS, (bx, by, w, h), 1, border_radius=5)
            for i, ln in enumerate(lines):
                text(ln, bx + 8, by + 6 + i * 16, F_S, INK if i else PHOS)

        # ---- metrics dashboard (toggle M): visualize the collected telemetry ----
        if metrics_mode and not world.over:
            ov = pygame.Surface((GW, WIN_H), pygame.SRCALPHA)
            ov.fill((8, 14, 22, 228))
            screen.blit(ov, (0, 0))
            tel = world.telemetry
            text("METRICS  (M to close)", 24, 20, F_M, PHOS)

            text("NODE QUEUES (peak depth)", 24, 56, F_S, MUTED)
            nodes = tel.node_summary()
            max_q = max((nw.peak_queue for nw in nodes.values()), default=1) or 1
            yy = 76
            for nid in world.map.nodes:
                nw = nodes.get(nid)
                pk = nw.peak_queue if nw else 0
                drops = nw.overflow_drops if nw else 0
                col = DANGER if drops else PHOS
                pygame.draw.rect(screen, col, (120, yy, max(1, int(220 * pk / max_q)), 10))
                text(nid, 24, yy - 2, F_S, INK)
                text(f"{pk}" + (f"  drop {drops}" if drops else ""), 350, yy - 2, F_S, col)
                yy += 16

            text("BY KIND  (handled / leaked)", 24, yy + 14, F_S, MUTED)
            yy += 34
            kinds = tel.kind_summary()
            max_s = max((kw.spawned for kw in kinds.values()), default=1) or 1
            for k, kw in kinds.items():
                if kw.spawned == 0:
                    continue
                pygame.draw.rect(screen, KINDS[k]["color"],
                                 (120, yy, max(1, int(200 * kw.handled / max_s)), 6))
                pygame.draw.rect(screen, DANGER,
                                 (120, yy + 7, max(0, int(200 * kw.leaked / max_s)), 6))
                text(k, 24, yy - 1, F_S, INK)
                text(f"{kw.handled}/{kw.leaked}", 330, yy - 1, F_S, INK)
                yy += 20

            text("HEALTH TREND", 24, yy + 14, F_S, MUTED)
            yy += 32
            pts = [tp.health for tp in tel.trend][-120:]
            for i in range(1, len(pts)):
                span = len(pts) - 1
                a = (120 + (i - 1) * 240 / span, yy + 40 - pts[i - 1] / START_HEALTH * 40)
                b = (120 + i * 240 / span, yy + 40 - pts[i] / START_HEALTH * 40)
                pygame.draw.line(screen, PHOS, a, b, 1)
            eff = tel.efficiency(world)
            text(f"cost / handled: {eff['cost_per_handled']:.0f}cr", 24, yy + 52, F_S, INK)

        if world.over:
            ov = pygame.Surface((GW, WIN_H), pygame.SRCALPHA)
            ov.fill((8, 14, 22, 210))
            screen.blit(ov, (0, 0))
            msg = "PIPELINE HELD" if world.won else "PIPELINE OVERWHELMED"
            text(msg, GW // 2 - 110, 60, F_L, PHOS if world.won else DANGER)
            if not world.won:
                # incident post-mortem: what failed, on which kinds and nodes
                deb = summarize_failure(world)
                text(deb.cause, 40, 100, F_S, INK)
                text("WHERE IT BROKE", 40, 132, F_S, MUTED)
                for i, ln in enumerate(deb.lines[:6]):
                    text("- " + ln, 48, 152 + i * 18, F_S, DANGER)
            text("Press R to retry, or edit loadout.py and F5.",
                 GW // 2 - 150, WIN_H - 80, F_S, INK)

        pygame.display.flip()

    pygame.quit()
