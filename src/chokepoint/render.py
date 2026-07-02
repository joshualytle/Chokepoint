"""Pygame renderer + tooltips + map switching + loadout hot-reload + LLM helper.

Run: ``python -m chokepoint``. Logic lives in the other modules; this only
draws state and handles input.

Controls:
  [ / ]   previous / next map        R   reset
  P       pause / resume             .   step one tick while paused
  F5      reload your loadout.py
  E       toggle the placement editor (buy/place/equip/remove turrets)
  T       toggle build mode (design the topology: add nodes/edges)
  C       edit loadout.py in-app (Ctrl+S apply, Esc close)
  M       toggle the metrics dashboard (queues, by-kind, health trend)
  H       toggle the help overlay (controls + kind/gun legend)
  S       save the current build to loadout.py (resume it next launch / F5)
  D       cycle difficulty (easy / adaptive / overkill) — resets the run
  F       fast-forward: cycle sim speed 1x / 2x / 3x
  K       sandbox: toggle free credits to experiment (resets the run)
  L       ask your local LLM for help (optional; off-thread, never freezes)
  hover   a turret or a legend swatch for a tooltip

Editor (press E): click a gun in the palette (or 1-9) to select it, click a
module row to queue it, then left-click the map to place. Left-click an existing
turret to equip your queued modules onto it; right-click to remove (full refund).
Pick the gate router (G) and left-click near a fork to place a gate; it
auto-routes each kind to the branch whose consumers can handle it. Pick the
quelimiter (B) and left-click a node to place a buffer that smooths a burst.
Everything is charged against your credits, which grow as you clear waves.
"""

from __future__ import annotations

import asyncio
import importlib
import math
import os
import sys
import threading
from typing import Any

from . import llm_assist
from . import loadout as loadout_mod
from .arsenal import GUN_LIBRARY, MODULE_LIBRARY, active_synergies, gun_cost, make_gun
from .codebuffer import TextBuffer
from .editor import ArsenalEditor
from .gates import DEFAULT_GATE_COST
from .hints import coaching
from .lessons import Lessons
from .limiter import DEFAULT_LIMITER_COST
from .maps import GW, MAP_LIST, MAPS
from .metrics import summarize_failure
from .packets import DIFFICULTY_LIST, KINDS
from .scores import load_highscore, save_highscore
from .simulation import (
    DWELL_GRACE,
    MAX_LEAK,
    QUEUE_CAP,
    START_HEALTH,
    STARTING_CREDITS,
    World,
)
from .syntax import spans as code_spans
from .tutorial import Tutorial

QUEUE_WARN = QUEUE_CAP - 2  # queue depth at which a node's marker turns red


async def main() -> None:  # pragma: no cover - needs a display
    # pygbag (pygame -> WASM) requires an async entry point and one
    # ``await asyncio.sleep(0)`` per frame so the browser event loop can run.
    # ``asyncio.run(main())`` works identically on the desktop, so the same
    # loop drives both the native and web builds.
    import pygame

    pygame.init()
    pygame.key.set_repeat(250, 30)
    WIN_W, WIN_H = 1100, 680
    LESSON_X = int(WIN_W * 0.56)   # left edge of the lessons panel in the code editor
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Chokepoint — typed turrets vs an alert flood")
    clock = pygame.time.Clock()

    mono_ttf = os.path.join(os.path.dirname(__file__), "assets", "DejaVuSansMono.ttf")

    def font(sz: int, bold: bool = False):
        # SysFont enumerates installed fonts, which hangs under WASM (no fontconfig
        # in Pyodide). On the web build load the bundled DejaVu Sans Mono instead —
        # pygame's default font is a heavy sans that's mushy at small sizes.
        if sys.platform == "emscripten":
            f = pygame.font.Font(mono_ttf, sz)
            f.set_bold(bold)
            return f
        return pygame.font.SysFont("menlo,consolas,dejavusansmono,monospace", sz, bold=bold)

    F_S, F_M, F_L = font(13), font(15), font(20, True)

    BG = (14, 22, 34)
    PANEL = (19, 31, 46)
    PANEL2 = (11, 19, 32)
    GRID = (28, 44, 62)
    INK = (226, 236, 244)   # brighter than before for legibility on the dark UI
    MUTED = (150, 170, 188)
    PHOS = (56, 225, 176)
    DANGER = (229, 85, 110)
    GATE_C = (240, 200, 120)
    AMBER = (242, 200, 90)
    PARSER_C = (190, 150, 255)

    map_i = 0
    difficulty_i = 0
    world = World(MAPS[MAP_LIST[map_i]].copy(), difficulty=DIFFICULTY_LIST[difficulty_i])
    editor = ArsenalEditor(world.unlocked(), bank=world.bank)
    edit_mode = False
    metrics_mode = False
    help_mode = False
    drag_item: tuple[str, str] | None = None  # (kind, name) being dragged from the palette
    build_mode = False           # topology editing: add/remove nodes and edges
    edge_src: str | None = None  # first node picked while drawing an edge
    NODE_PICK = 16               # click within this many px counts as clicking a node
    code_mode = False            # in-app code editor for loadout.py
    code_buf = TextBuffer()
    code_status: dict[str, str] = {"msg": ""}
    code_scroll = 0              # first visible line in the editor (mouse-wheel scroll)
    tutorial = Tutorial()        # guided onboarding; freezes the sim until done/skipped
    tut_next: Any = None         # Rect of the on-screen Next/Start button (set while drawing)
    tut_skip: Any = None         # Rect of the Skip button
    lessons = Lessons()          # in-editor Python lessons (shown beside the C editor)
    les_next: Any = None         # Rects for the lessons panel buttons (set while drawing)
    les_skip: Any = None
    les_start: Any = None
    speed = 1                    # sim speed multiplier (F cycles 1x/2x/3x)
    sandbox = False              # practice mode: free credits to experiment (K)
    prev_wave = 0                # to announce wave clears
    awaiting_start = True        # paused before each wave so you can prep; P/SPACE begins
    HISCORE_PATH = "chokepoint_highscore.txt"
    end_score = {"saved": False, "score": 0, "best": load_highscore(HISCORE_PATH)}
    # palette rows registered each frame so panel clicks can be mapped to actions:
    # (rect, "gun"|"mod", name)
    palette_hits: list[tuple[Any, str, str]] = []
    llm_state: dict[str, str] = {"status": "idle", "text": "Press L for local-LLM help."}
    # transient action feedback, shown in every mode (unlike the LLM box)
    toast: dict[str, Any] = {"text": "", "ttl": 0.0, "ok": True}

    def say(text: str, ok: bool = True) -> None:
        toast["text"], toast["ttl"], toast["ok"] = text, 2.5, ok

    def deploy_loadout(refund_current: bool = False, load_topology: bool = True) -> None:
        """(Re)build turrets from loadout.py, costed against the budget.

        The editor is the single source of truth; loadout.py is its initial paid
        build. ``refund_current`` (used by F5) returns the cost of whatever is
        deployed before re-buying, so reloading the file never double-charges.
        ``load_topology`` applies a saved custom map (skipped when switching maps).
        """
        nonlocal editor
        build_topology = getattr(loadout_mod, "build_topology", None)
        if load_topology and build_topology is not None:
            world.map = build_topology()   # resume a designed map
            world.packets.clear()
        if refund_current:
            for t in world.turrets:
                world.bank.earn(gun_cost(t.gun))
            for gt in world.gates:
                world.bank.earn(gt.cost)
            for lm in world.limiters:
                world.bank.earn(lm.cost)
            for ps in world.parsers:
                world.bank.earn(ps.cost)
        editor = ArsenalEditor(world.unlocked(), bank=world.bank)
        dropped = editor.seed_purchase(
            loadout_mod.build_loadout(world.unlocked(), world.map.slots)
        )
        # gates / limiters are optional in a saved loadout (older files lack them)
        build_gates = getattr(loadout_mod, "build_gates", None)
        if build_gates is not None:
            editor.seed_purchase_gates(build_gates(world.unlocked(), world.map.slots))
        build_limiters = getattr(loadout_mod, "build_limiters", None)
        if build_limiters is not None:
            editor.seed_purchase_limiters(build_limiters(world.unlocked(), world.map.slots))
        # parsers decode raw alerts; only relevant (and only charged) on the
        # "ingest" difficulty, which is the profile that emits raw traffic.
        parsers = []
        build_parsers = getattr(loadout_mod, "build_parsers", None)
        if build_parsers is not None and world.difficulty == "ingest":
            for ps in build_parsers(world.unlocked(), world.map.slots):
                if world.bank.spend(ps.cost):
                    parsers.append(ps)
        world.set_parsers(parsers)
        sync_world()
        if dropped:
            say(f"Over budget: {len(dropped)} loadout turret(s) not deployed.", ok=False)

    def sync_world() -> None:
        """Push the editor's turrets, gates, and limiters to the world; re-route."""
        world.set_turrets(editor.to_turrets())
        world.set_gates(editor.to_gates())
        world.set_limiters(editor.to_limiters())
        world.autoroute()

    def node_under(mx: int, my: int) -> str | None:
        """The node id under a click (within NODE_PICK px), or None for empty space."""
        if not world.map.nodes:
            return None
        nid = world.map.nearest_node(mx, my)
        nx, ny = world.map.pos(nid)
        return nid if (nx - mx) ** 2 + (ny - my) ** 2 <= NODE_PICK * NODE_PICK else None

    def topology_edited() -> None:
        """After a structural change: drop in-flight packets (they may reference a
        removed node) and re-snap devices."""
        world.packets.clear()
        world.rebind()

    def apply_code(src: str) -> None:
        """Validate the edited loadout source, then write + reload + redeploy.

        We compile and dry-run build_loadout first, so a syntax/author error is
        reported in the editor and the on-disk loadout.py is never corrupted.
        """
        ns: dict = {}
        try:
            exec(compile(src, loadout_mod.__file__, "exec"), ns)  # noqa: S102 - intended in-app eval
            if "build_loadout" not in ns:
                raise ValueError("define build_loadout(unlocked, slots)")
            ns["build_loadout"](world.unlocked(), world.map.slots)
        except Exception as err:  # surface any author error; never crash the loop
            code_status["msg"] = f"error: {err}"
            say("code not applied — see editor", ok=False)
            return
        with open(loadout_mod.__file__, "w", encoding="utf-8") as fh:
            fh.write(src)
        importlib.reload(loadout_mod)
        deploy_loadout(refund_current=True)
        code_status["msg"] = "applied OK"
        say("loadout applied from editor")

    def switch_map(delta: int) -> None:
        nonlocal map_i, world, edit_mode, awaiting_start
        map_i = (map_i + delta) % len(MAP_LIST)
        world = World(MAPS[MAP_LIST[map_i]].copy(), difficulty=DIFFICULTY_LIST[difficulty_i])
        edit_mode = False
        deploy_loadout(load_topology=False)  # an explicit map choice ignores the saved one
        awaiting_start = True               # start the new map paused on its wave preview

    def ask_llm() -> None:
        llm_state["status"] = "thinking"
        llm_state["text"] = "Asking your local LLM..."

        def work() -> None:
            ctx = llm_assist.state_summary(world)
            llm_state["text"] = llm_assist.diagnose(
                ctx, "What is leaking and how should I change my loadout to fix it?"
            )
            llm_state["status"] = "done"

        if sys.platform == "emscripten":
            # Pyodide has no real threads and the browser sandbox blocks raw
            # sockets, so the local-LLM helper can't run on the web build.
            llm_state["status"] = "done"
            llm_state["text"] = "Local-LLM help is unavailable in the browser build."
            return
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

    # Start with a CLEAN board — you build it (guided by the tutorial/coach), or
    # press F5 to load the example loadout.py. sync_world pushes the empty editor.
    sync_world()
    world.set_parsers([])

    def text(s: str, x: int, y: int, f=F_S, c=INK) -> None:
        screen.blit(f.render(s, True, c), (x, y))

    def tooltip(lines: list[str], accent=PHOS) -> None:
        """Draw a hover tooltip box at the cursor; first line is the accented title."""
        w = max(F_S.size(s)[0] for s in lines) + 16
        h = len(lines) * 16 + 10
        bx, by = min(mouse[0] + 12, GW - w), min(mouse[1] + 12, WIN_H - h)
        pygame.draw.rect(screen, PANEL2, (bx, by, w, h), border_radius=5)
        pygame.draw.rect(screen, accent, (bx, by, w, h), 1, border_radius=5)
        for i, ln in enumerate(lines):
            text(ln, bx + 8, by + 6 + i * 16, F_S, INK if i else accent)

    PANEL_X = GW + 10
    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        mouse = pygame.mouse.get_pos()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif (tutorial.active and ev.type == pygame.MOUSEBUTTONDOWN
                  and tut_next is not None and tut_next.collidepoint(ev.pos)):
                tutorial.next()     # the Next/Start button advances a manual step
            elif (tutorial.active and ev.type == pygame.MOUSEBUTTONDOWN
                  and tut_skip is not None and tut_skip.collidepoint(ev.pos)):
                tutorial.skip()     # other clicks fall through, so building still works
            elif ev.type == pygame.KEYDOWN and code_mode:
                # the code editor captures all typing while open
                if ev.key == pygame.K_ESCAPE:
                    code_mode = False
                elif (ev.mod & pygame.KMOD_CTRL) and ev.key == pygame.K_s:
                    apply_code(code_buf.text())
                elif (ev.mod & pygame.KMOD_CTRL) and ev.key == pygame.K_z:
                    code_buf.undo()
                elif ev.key == pygame.K_RETURN:
                    code_buf.newline()
                elif ev.key == pygame.K_BACKSPACE:
                    code_buf.backspace()
                elif ev.key == pygame.K_DELETE:
                    code_buf.delete()
                elif ev.key == pygame.K_LEFT:
                    code_buf.left()
                elif ev.key == pygame.K_RIGHT:
                    code_buf.right()
                elif ev.key == pygame.K_UP:
                    code_buf.up()
                elif ev.key == pygame.K_DOWN:
                    code_buf.down()
                elif ev.key == pygame.K_HOME:
                    code_buf.home()
                elif ev.key == pygame.K_END:
                    code_buf.end()
                elif ev.key == pygame.K_TAB:
                    code_buf.insert("    ")
                elif ev.unicode and ev.unicode.isprintable():
                    code_buf.insert(ev.unicode)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_LEFTBRACKET:
                    switch_map(-1)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    switch_map(1)
                elif ev.key == pygame.K_r:
                    world.reset()
                    deploy_loadout()
                    awaiting_start = True
                elif ev.key in (pygame.K_p, pygame.K_SPACE):
                    if awaiting_start:
                        awaiting_start = False   # begin the pending wave
                        world.paused = False
                    else:
                        world.paused = not world.paused
                elif ev.key == pygame.K_PERIOD and world.paused and not world.over:
                    world.step(1 / 60)  # single-step one tick while paused
                elif ev.key == pygame.K_F5:
                    importlib.reload(loadout_mod)
                    deploy_loadout(refund_current=True)
                    say("Loadout reloaded from loadout.py")
                elif ev.key == pygame.K_e:
                    edit_mode = not edit_mode
                    if edit_mode:
                        build_mode = False
                        tutorial.signal("edit")
                elif ev.key == pygame.K_t:
                    build_mode = not build_mode
                    edge_src = None
                    if build_mode:
                        edit_mode = False
                elif ev.key == pygame.K_m:
                    metrics_mode = not metrics_mode
                elif ev.key == pygame.K_h:
                    help_mode = not help_mode
                elif ev.key == pygame.K_c:
                    try:
                        with open(loadout_mod.__file__, encoding="utf-8") as fh:
                            code_buf.set_text(fh.read())
                    except OSError as err:
                        code_buf.set_text(f"# could not read loadout.py: {err}\n")
                    code_status["msg"] = ""
                    code_scroll = 0
                    code_mode = True
                    tutorial.signal("code")
                elif ev.key == pygame.K_s:
                    # save the current build to loadout.py so it loads next launch
                    try:
                        with open(loadout_mod.__file__, "w", encoding="utf-8") as fh:
                            fh.write(editor.to_python(world.map))
                        say("Saved build + topology to loadout.py")
                    except OSError as err:
                        say(f"Save failed: {err}", ok=False)
                elif ev.key == pygame.K_d:
                    difficulty_i = (difficulty_i + 1) % len(DIFFICULTY_LIST)
                    world.difficulty = DIFFICULTY_LIST[difficulty_i]
                    world.reset()
                    deploy_loadout()
                    awaiting_start = True
                    say(f"difficulty: {world.difficulty} (run reset)")
                elif ev.key == pygame.K_l:
                    ask_llm()
                elif ev.key == pygame.K_f:
                    speed = speed % 3 + 1  # 1x -> 2x -> 3x -> 1x
                elif ev.key == pygame.K_k:
                    sandbox = not sandbox  # practice mode: free credits
                    credits = 100000 if sandbox else STARTING_CREDITS
                    world = World(MAPS[MAP_LIST[map_i]].copy(),
                                  difficulty=DIFFICULTY_LIST[difficulty_i],
                                  starting_credits=credits)
                    deploy_loadout(load_topology=False)
                    awaiting_start = True
                    say("sandbox ON — free credits to experiment" if sandbox
                        else "sandbox off")
                elif edit_mode and ev.key == pygame.K_g:
                    editor.select_gate()  # gate-placement mode
                elif edit_mode and ev.key == pygame.K_b:
                    editor.select_limiter()  # quelimiter (buffer) placement mode
                elif edit_mode and ev.key == pygame.K_x:
                    for t in editor.to_turrets():    # clear all placements, refunded
                        world.bank.earn(gun_cost(t.gun))
                    for gt in editor.to_gates():
                        world.bank.earn(gt.cost)
                    for lm in editor.to_limiters():
                        world.bank.earn(lm.cost)
                    editor.clear()
                    sync_world()
                    say("cleared all placements (refunded)")
                elif edit_mode and pygame.K_1 <= ev.key <= pygame.K_9:
                    guns = editor.available_guns()
                    idx = ev.key - pygame.K_1
                    if idx < len(guns):
                        editor.select_gun(guns[idx])
            elif ev.type == pygame.MOUSEWHEEL and code_mode:
                code_scroll = max(0, code_scroll - ev.y * 3)  # scroll the code view
            elif (ev.type == pygame.MOUSEBUTTONDOWN and code_mode and ev.button == 1
                  and les_next is not None and les_next.collidepoint(ev.pos)):
                lessons.next()
            elif (ev.type == pygame.MOUSEBUTTONDOWN and code_mode and ev.button == 1
                  and les_skip is not None and les_skip.collidepoint(ev.pos)):
                lessons.skip()
            elif (ev.type == pygame.MOUSEBUTTONDOWN and code_mode and ev.button == 1
                  and les_start is not None and les_start.collidepoint(ev.pos)):
                lessons.start()
            elif (ev.type == pygame.MOUSEBUTTONDOWN and code_mode and ev.button == 1
                  and ev.pos[0] < LESSON_X - 14):  # caret positioning in the code area only
                mx, my = ev.pos
                top, left = 56, 52
                r = code_scroll + (my - top) // 16
                if my >= top and 0 <= r < len(code_buf.lines):
                    code_buf.row = r
                    ln = code_buf.lines[r]
                    c = 0
                    while c < len(ln) and left + F_S.size(ln[: c + 1])[0] <= mx:
                        c += 1
                    code_buf.col = c
            elif ev.type == pygame.MOUSEBUTTONDOWN and edit_mode and not code_mode:
                mx, my = ev.pos
                if mx < GW:  # click on the playfield -> place / equip / remove
                    if ev.button == 1:
                        if editor.placing_limiter:
                            editor.place_limiter(mx, my)
                        elif editor.placing_gate:
                            editor.place_gate(mx, my)
                        else:
                            hit = editor.turret_at(mx, my)
                            if hit is not None and editor.pending_modules:
                                for m in list(editor.pending_modules):
                                    editor.equip_at(mx, my, m)
                            else:
                                editor.place(mx, my)
                        sync_world()
                    elif ev.button == 3:  # remove a turret, gate, or limiter under the cursor
                        if (editor.remove_at(mx, my) or editor.remove_gate_at(mx, my)
                                or editor.remove_limiter_at(mx, my)):
                            sync_world()
                elif ev.button == 1:  # click on the panel -> palette selection
                    for rect, kind, name in palette_hits:
                        if rect.collidepoint(mx, my):
                            if kind == "gun":
                                editor.select_gun(name)
                            elif kind == "gate":
                                editor.select_gate()
                            elif kind == "limiter":
                                editor.select_limiter()
                            else:
                                editor.toggle_module(name)
                            # placeable items can also be dragged onto the map
                            if kind in ("gun", "gate", "limiter"):
                                drag_item = (kind, name)
                            break
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and edit_mode and not code_mode:
                if drag_item is not None:
                    mx, my = ev.pos
                    kind, _ = drag_item
                    if mx < GW:  # dropped on the playfield -> place there
                        if kind == "gun":
                            editor.place(mx, my)
                        elif kind == "gate":
                            editor.place_gate(mx, my)
                        elif kind == "limiter":
                            editor.place_limiter(mx, my)
                        sync_world()
                    drag_item = None
            elif (ev.type == pygame.MOUSEBUTTONDOWN and build_mode and not code_mode
                  and ev.pos[0] < GW):
                mx, my = ev.pos
                picked = node_under(mx, my)
                if ev.button == 1:
                    if picked is None:                # empty space -> new node
                        world.map.add_node(mx, my)
                        topology_edited()
                        say("added node")
                    elif edge_src is None:            # first node of an edge
                        edge_src = picked
                    else:                             # second node -> draw the edge
                        if world.map.add_edge(edge_src, picked):
                            topology_edited()
                            say(f"edge {edge_src} → {picked}")
                        else:
                            say("edge rejected (would loop, or duplicate)", ok=False)
                        edge_src = None
                elif ev.button == 3:                  # remove a node
                    if picked is not None and world.map.remove_node(picked):
                        topology_edited()
                        say(f"removed {picked}")
                    else:
                        say("can't remove (source/sink or empty space)", ok=False)
                    edge_src = None

        # keep the editor palette in step with what the current wave has unlocked
        editor.set_unlocked(world.unlocked())
        if tutorial.active:
            tutorial.maybe_advance(world, editor)  # advance any state-gated step
        if awaiting_start:
            world.paused = True   # hold on the wave preview until the player begins

        if not world.paused and not world.over and not code_mode and not tutorial.active:
            acc = dt * speed  # fast-forward runs more sim time per frame
            while acc > 0:
                world.step(min(1 / 60, acc))
                acc -= 1 / 60
        if world.wave_idx > prev_wave and not world.over:  # announce a wave clear
            say(f"Wave {world.wave_idx} cleared!  +{world.wave_income(world.wave_idx)} credits")
            awaiting_start = True   # prep pause: build/adjust before starting the next wave
        prev_wave = world.wave_idx

        coach = coaching(world)  # live advice; top one is shown, all listed in metrics
        coach_c = {"danger": DANGER, "warn": AMBER, "tip": (130, 170, 255), "ok": PHOS}

        # ---- draw playfield ----
        screen.fill(BG)
        for x in range(0, GW, 40):
            pygame.draw.line(screen, GRID, (x, 0), (x, WIN_H))
        for y in range(0, WIN_H, 40):
            pygame.draw.line(screen, GRID, (0, y), (GW, y))
        # ---- topology: edges (with a flow-direction arrow), then nodes ----
        for src, dst in world.map.edges():
            ax, ay = world.map.pos(src)
            bx, by = world.map.pos(dst)
            pygame.draw.line(screen, (42, 66, 89), (ax, ay), (bx, by), 12)
            dist = math.hypot(bx - ax, by - ay) or 1.0
            ux, uy = (bx - ax) / dist, (by - ay) / dist  # unit + perpendicular
            mx2, my2 = ax + (bx - ax) * 0.55, ay + (by - ay) * 0.55
            tip = (mx2 + ux * 7, my2 + uy * 7)
            b1 = (mx2 - ux * 3 - uy * 5, my2 - uy * 3 + ux * 5)
            b2 = (mx2 - ux * 3 + uy * 5, my2 - uy * 3 - ux * 5)
            pygame.draw.polygon(screen, (70, 100, 130), [tip, b1, b2])
        worst_node, worst_depth = None, 0  # the live bottleneck this frame
        for nid, node in world.map.nodes.items():
            q = world.queue_at(nid)
            depth = len(q)
            nx, ny = int(node.x), int(node.y)
            if nid == world.map.sink:
                pygame.draw.rect(screen, DANGER, (nx - 8, ny - 20, 7, 40))
            # live load heat: green when clear, amber as it fills, red near overflow
            frac = depth / QUEUE_CAP
            load_c = PHOS if frac < 0.34 else (AMBER if frac < 0.67 else DANGER)
            pygame.draw.circle(screen, load_c, (nx, ny), 5 + min(depth, QUEUE_CAP))
            if depth:
                text(str(depth), nx + 9, ny - 7, F_S, load_c)
            if depth > worst_depth:
                worst_node, worst_depth = (nx, ny), depth
            # queued packets stacked beside the node (size shrinks as volume drains)
            for j, p in enumerate(q):
                r = max(3, int(6 * p.volume / p.maxvol))
                pygame.draw.circle(screen, KINDS[p.kind]["color"],
                                   (nx + 14 + (j % 4) * 8, ny - 14 + (j // 4) * 8), r)
        # call out the current bottleneck once it's genuinely backing up
        if worst_node is not None and worst_depth > QUEUE_WARN:
            pygame.draw.circle(screen, DANGER, worst_node, 22, 2)
            text("BOTTLENECK", worst_node[0] - 34, worst_node[1] + 24, F_S, DANGER)
            text("add a turret, a limiter (B), or a parallel branch (T) to spill into",
                 worst_node[0] - 150, worst_node[1] + 40, F_S, AMBER)

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

        # limiters: a valve marker at the node, with its buffered count
        for lm in world.limiters:
            if lm.node not in world.map.nodes:
                continue
            lx, ly = (int(v) for v in world.map.pos(lm.node))
            pygame.draw.rect(screen, BG, (lx - 9, ly - 9, 18, 18))
            pygame.draw.rect(screen, AMBER, (lx - 9, ly - 9, 18, 18), 2)
            pygame.draw.line(screen, AMBER, (lx, ly - 9), (lx, ly + 9), 2)
            text(lm.id, lx - 8, ly - 30, F_S, AMBER)

        # parsers: a hexagon decoder at the node, with a swatch per handled kind
        for ps in world.parsers:
            if ps.node not in world.map.nodes:
                continue
            px, py = (int(v) for v in world.map.pos(ps.node))
            hexagon = [(px + 11, py), (px + 5, py + 10), (px - 5, py + 10),
                       (px - 11, py), (px - 5, py - 10), (px + 5, py - 10)]
            pygame.draw.polygon(screen, BG, hexagon)
            pygame.draw.polygon(screen, PARSER_C, hexagon, 2)
            text(ps.id, px - 8, py - 32, F_S, PARSER_C)
            for ci, k in enumerate(sorted(ps.handles)):
                pygame.draw.rect(screen, KINDS[k]["color"], (px - 14 + ci * 5, py + 13, 4, 4))

        # placement preview: highlight what a click would bind to
        if edit_mode and mouse[0] < GW and editor.placing_limiter:
            col = PHOS if world.bank.can_afford(editor.pending_cost()) else DANGER
            nid = world.map.nearest_node(mouse[0], mouse[1])
            fx, fy = (int(v) for v in world.map.pos(nid))
            pygame.draw.line(screen, col, mouse, (fx, fy), 1)
            pygame.draw.rect(screen, col, (fx - 10, fy - 10, 20, 20), 2)
        elif edit_mode and mouse[0] < GW and editor.placing_gate:
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

        # build mode: ring every node, mark source/sink, draw the pending edge
        if build_mode:
            for nid in world.map.nodes:
                nx, ny = (int(v) for v in world.map.pos(nid))
                ring = GATE_C if nid in (world.map.source, world.map.sink) else PHOS
                pygame.draw.circle(screen, ring, (nx, ny), 16, 1)
                text(nid, nx + 10, ny + 6, F_S, MUTED)  # label so you can see what you connect
            sx, sy = (int(v) for v in world.map.pos(world.map.source))
            kx, ky = (int(v) for v in world.map.pos(world.map.sink))
            text("src", sx - 9, sy + 18, F_S, GATE_C)
            text("sink", kx - 12, ky + 18, F_S, GATE_C)
            if edge_src is not None:
                pygame.draw.line(screen, PHOS, world.map.pos(edge_src), mouse, 2)
            text("BUILD MODE (T) — click empty = node · node→node = edge · RMB node = remove",
                 12, 14, F_S, PHOS)

        if ((world.intermission > 0 or awaiting_start) and not world.over
                and not build_mode and not tutorial.active):
            title = (f"Wave {world.level} ready — press  P  or  SPACE  to begin"
                     if awaiting_start else f"Wave {world.level} incoming...")
            text(title, GW // 2 - F_M.size(title)[0] // 2, 12, F_M,
                 AMBER if awaiting_start else INK)
            # preview the upcoming kinds with swatches so you can prep coverage
            preview = list(world.upcoming_kinds().items())
            labels = [f"{k} x{n}" for k, n in preview]
            total_w = sum(20 + F_S.size(s)[0] for s in labels)
            px = GW // 2 - total_w // 2
            for (k, _n), label in zip(preview, labels, strict=True):
                pygame.draw.rect(screen, KINDS[k]["color"], (px, 40, 8, 8))
                text(label, px + 12, 38, F_S, INK)
                px += 20 + F_S.size(label)[0]
        text(f"map: {world.map.name}   [ ] to switch", 12, WIN_H - 22, F_S, MUTED)
        speed_txt = f"   speed x{speed} (F)" if speed > 1 else "   F to fast-forward"
        sand_txt = "   · SANDBOX" if sandbox else ""
        text(f"mode: {world.difficulty}   D to cycle{speed_txt}{sand_txt}   ·   H for help",
             12, WIN_H - 40, F_S, PHOS if sandbox else MUTED)
        # live coach: the single most important thing to fix — a teaching card
        # (symptom + why + fix + concept) when something's wrong, one line when clear
        if coach and not build_mode and not code_mode and not world.over and not tutorial.active:
            h = coach[0]
            if h.level == "ok":
                text("COACH: " + h.text, 12, WIN_H - 78, F_S, coach_c["ok"])
            else:
                pw = int(GW * 0.62)
                clines: list[tuple[str, Any]] = [(f"COACH  >  {h.text}", coach_c[h.level])]
                for j, ln in enumerate(wrap(h.why, pw - 28, F_S)):
                    clines.append((("WHY:  " if j == 0 else "      ") + ln, INK))
                for j, ln in enumerate(wrap(h.fix, pw - 28, F_S)):
                    clines.append((("FIX:  " if j == 0 else "      ") + ln, AMBER))
                if h.concept:
                    clines.append((f"concept: {h.concept}", MUTED))
                ph = len(clines) * 16 + 14
                py = WIN_H - 96 - ph
                pygame.draw.rect(screen, PANEL2, (10, py, pw, ph), border_radius=6)
                pygame.draw.rect(screen, coach_c[h.level], (10, py, pw, ph), 1, border_radius=6)
                for j, (ln, c) in enumerate(clines):
                    text(ln, 20, py + 8 + j * 16, F_S, c)
        # transient action feedback (save/reload/over-budget/difficulty), always visible
        if toast["ttl"] > 0:
            toast["ttl"] -= dt
            text(toast["text"], 12, WIN_H - 60, F_S, PHOS if toast["ok"] else DANGER)

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
        gap_kinds = world.coverage_gaps()
        for k, s in world.stats.items():
            if s.spawned == 0:
                continue
            pygame.draw.rect(screen, KINDS[k]["color"], (PANEL_X, row + 2, 8, 8))
            gap = k in gap_kinds
            mark = "!" if gap else " "  # uncovered kinds flagged before they pile up
            line = f"{mark}{k:<9} {s.spawned:>3} {s.handled:>3} {s.leaked:>4} {s.inflight:>4}"
            text(line, PANEL_X + 14, row, F_S, DANGER if (gap or s.leaked) else INK)
            row += 18

        row += 8
        text("UNLOCKED: " + ", ".join(sorted(world.unlocked())), PANEL_X, row, F_S, MUTED)
        row += 18
        syns = active_synergies(world.turrets)
        if syns:
            text("SYNERGY: " + ", ".join(s.name for s in syns), PANEL_X, row, F_S, PHOS)
        row += 18

        panel_w = WIN_W - PANEL_X - 14
        palette_hits.clear()
        if edit_mode:
            text("EDIT MODE — E to exit", PANEL_X, row, F_S, PHOS)
            row += 18
            text("drag/click place · LMB turret=equip · RMB remove · X clear all",
                 PANEL_X, row, F_S, MUTED)
            row += 20
            text("GUNS — click one, then click a node to place it", PANEL_X, row, F_S, AMBER)
            row += 20
            for i, name in enumerate(editor.available_guns()):
                g = make_gun(name)
                sel = name == editor.selected_gun
                affordable = world.bank.can_afford(g.cost)
                card = pygame.Rect(PANEL_X, row, panel_w, 30)
                hover = card.collidepoint(mouse)
                # every gun is a clear button: subtle fill always, outline on hover,
                # green fill + border when selected
                pygame.draw.rect(screen, (26, 52, 46) if sel else PANEL, card, border_radius=5)
                if sel:
                    pygame.draw.rect(screen, PHOS, card, 2, border_radius=5)
                elif hover and affordable:
                    pygame.draw.rect(screen, GRID, card, 1, border_radius=5)
                palette_hits.append((card, "gun", name))
                name_c = PHOS if sel else (INK if affordable else MUTED)
                text(f"{i + 1}", PANEL_X + 8, row + 5, F_S, MUTED)
                text(name, PANEL_X + 26, row + 3, F_M, name_c)
                cost_s = f"{g.cost}cr"
                text(cost_s, PANEL_X + panel_w - 10 - F_S.size(cost_s)[0], row + 5, F_S,
                     name_c if affordable else DANGER)
                # alert types it handles, as colored labels (clearer than tiny dots)
                kx = PANEL_X + 26
                for k in sorted(g.accepts):
                    pygame.draw.rect(screen, KINDS[k]["color"], (kx, row + 20, 6, 6))
                    text(k, kx + 9, row + 17, F_S, KINDS[k]["color"])
                    kx += 9 + F_S.size(k)[0] + 9
                row += 33
                row += 17
            row += 6
            text("MODULES  (click to queue)", PANEL_X, row, F_S, MUTED)
            row += 17
            mods = editor.available_modules()
            col_w = panel_w // 2
            for i, name in enumerate(mods):  # two columns to save vertical space
                mod = MODULE_LIBRARY[name]
                queued = name in editor.pending_modules
                color = PHOS if queued else (INK if world.bank.can_afford(mod.cost) else MUTED)
                cellx = PANEL_X + (i % 2) * col_w
                celly = row + (i // 2) * 17
                palette_hits.append((pygame.Rect(cellx, celly - 1, col_w, 17), "mod", name))
                text(f"[{'x' if queued else ' '}] {name} {mod.cost}", cellx + 2, celly, F_S, color)
            row += ((len(mods) + 1) // 2) * 17 + 6
            text("FLOW DEVICES  (click, G gate / B limiter)", PANEL_X, row, F_S, MUTED)
            row += 17
            gcolor = GATE_C if editor.placing_gate else (
                INK if world.bank.can_afford(DEFAULT_GATE_COST) else MUTED)
            palette_hits.append((pygame.Rect(PANEL_X, row - 1, panel_w, 17), "gate", "gate"))
            text(f"gate    {DEFAULT_GATE_COST:>4}cr  routes kinds at a fork",
                 PANEL_X + 2, row, F_S, gcolor)
            row += 17
            lcolor = GATE_C if editor.placing_limiter else (
                INK if world.bank.can_afford(DEFAULT_LIMITER_COST) else MUTED)
            palette_hits.append((pygame.Rect(PANEL_X, row - 1, panel_w, 17), "limiter", "limiter"))
            text(f"limiter {DEFAULT_LIMITER_COST:>4}cr  buffers + smooths a burst",
                 PANEL_X + 2, row, F_S, lcolor)
            row += 21
            placing = ("limiter" if editor.placing_limiter else
                       "gate" if editor.placing_gate else editor.selected_gun)
            if placing is not None:
                sc = editor.pending_cost()
                color = PHOS if world.bank.can_afford(sc) else DANGER
                text(f"to place: {placing}  {sc}cr", PANEL_X, row, F_S, color)
        else:
            # LLM helper area
            pygame.draw.rect(screen, PANEL, (PANEL_X, row, panel_w, 150), border_radius=6)
            text("LOCAL LLM HELP  (press L)", PANEL_X + 10, row + 8, F_S, MUTED)
            for i, ln in enumerate(wrap(llm_state["text"], panel_w - 26, F_S)[:7]):
                text(ln, PANEL_X + 10, row + 28 + i * 16, F_S, INK)

        # hover tooltips (turret > gate > limiter > node), on top of everything
        hovered_node = node_under(mouse[0], mouse[1]) if mouse[0] < GW else None
        hovered_gate = next((g for g in world.gates if g.node == hovered_node), None)
        hovered_limiter = next((m for m in world.limiters if m.node == hovered_node), None)
        hovered_parser = next((ps for ps in world.parsers if ps.node == hovered_node), None)

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
            tooltip(lines)
        elif hovered_gate is not None:
            outs = world.map.branches(hovered_gate.node)
            lines = [f"{hovered_gate.id}: gate @ {hovered_gate.node}", "routes by kind:"]
            for i, bnode in enumerate(outs):
                routed = [k for k, idx in hovered_gate.routes.items() if idx == i]
                lines.append(f"  -> {bnode}: {', '.join(routed) if routed else '(none)'}")
            tooltip(lines, GATE_C)
        elif hovered_limiter is not None:
            buffered = [p for p in world.queue_at(hovered_limiter.node)
                        if not world.serves(hovered_limiter.node, p.kind)]
            tooltip([f"{hovered_limiter.id}: quelimiter @ {hovered_limiter.node}",
                     f"release {hovered_limiter.release_rate:.0f}/s",
                     f"buffered {len(buffered)}/{hovered_limiter.buffer_cap}"], AMBER)
        elif hovered_parser is not None:
            waiting_raw = [p for p in world.queue_at(hovered_parser.node) if p.kind == "raw"]
            stuck = sorted({p.payload for p in waiting_raw
                            if not hovered_parser.can_parse(p.payload)})
            p_lines = [f"{hovered_parser.id}: parser @ {hovered_parser.node}",
                       "decodes: " + ", ".join(sorted(hovered_parser.handles)),
                       f"raw decoded this run: {world.parsed}"]
            if stuck:
                p_lines.append("can't decode here: " + ", ".join(stuck))
            tooltip(p_lines, PARSER_C)
        elif hovered_node is not None:
            q = world.queue_at(hovered_node)
            cap = (world.limiter_at(hovered_node).buffer_cap  # type: ignore[union-attr]
                   if world.limiter_at(hovered_node) else QUEUE_CAP)
            served: set[str] = set()
            tput = 0.0
            for t in world.turrets:
                if t.node == hovered_node:
                    served |= t.accepts()
                    tput += t.dps()
            role = ("source" if hovered_node == world.map.source else
                    "sink" if hovered_node == world.map.sink else "node")
            node_lines = [f"{role} {hovered_node}", f"queue {len(q)}/{cap}",
                          "serves: " + (", ".join(sorted(served)) if served else "(pass-through)")]
            if tput:
                node_lines.append(f"throughput {tput:.0f}/s")
            aging = False
            if q:
                by_kind: dict[str, int] = {}
                for p in q:
                    by_kind[p.kind] = by_kind.get(p.kind, 0) + 1
                node_lines.append("queued: " + ", ".join(f"{k}x{n}"
                                                          for k, n in sorted(by_kind.items())))
                oldest = max(p.wait for p in q)
                aging = oldest > DWELL_GRACE
                node_lines.append(f"oldest wait {oldest:.1f}s / grace {DWELL_GRACE:.0f}s"
                                  + ("  -> BLEEDING HEALTH" if aging else ""))
                # kinds piling up that this node's own turrets can't accept (a local
                # specialization mismatch): they only drain if routed onward.
                if served:
                    unhandled = sorted(k for k in by_kind if k not in served)
                    if unhandled:
                        node_lines.append("not served here: " + ", ".join(unhandled))
            tooltip(node_lines, DANGER if aging else INK)

        # ---- help overlay (toggle H): controls + kind/gun legend ----
        if help_mode and not world.over:
            ov = pygame.Surface((GW, WIN_H), pygame.SRCALPHA)
            ov.fill((8, 14, 22, 235))
            screen.blit(ov, (0, 0))
            text("HELP — H to close", 24, 20, F_M, PHOS)
            controls = [
                ("[ ]", "previous / next map"), ("E", "placement editor"),
                ("G", "gate router (in editor)"), ("B", "quelimiter (in editor)"),
                ("T", "build mode (edit topology)"), ("C", "edit loadout.py in-app"),
                ("K", "sandbox (free credits)"), ("M", "metrics dashboard"),
                ("S", "save build to loadout.py"), ("D", "cycle difficulty"),
                ("P", "pause"), ("R", "reset"), ("F", "fast-forward (1/2/3x)"),
                ("F5", "reload loadout.py"), ("L", "local-LLM help"),
            ]
            text("CONTROLS", 24, 52, F_S, MUTED)
            yy = 70
            for key, desc in controls:
                text(f"{key:<4}", 28, yy, F_S, PHOS)
                text(desc, 70, yy, F_S, INK)
                yy += 17
            text("In the editor: LMB place · LMB+modules on a turret = equip · "
                 "RMB remove · gates snap to a fork", 24, yy + 2, F_S, MUTED)

            yy += 30
            text("ALERT KINDS", 24, yy, F_S, MUTED)
            yy += 18
            for k in KINDS:
                pygame.draw.rect(screen, KINDS[k]["color"], (28, yy + 2, 9, 9))
                text(f"{k:<11}{KINDS[k]['desc']}", 44, yy, F_S, INK)
                yy += 17

            yy += 14
            text("GUNS  (name  cost  accepts)", 24, yy, F_S, MUTED)
            yy += 18
            for name in GUN_LIBRARY:
                gun = make_gun(name)
                text(f"{name:<11}{gun.cost:>4}cr  {','.join(sorted(gun.accepts))}",
                     28, yy, F_S, INK)
                yy += 17
            text("Lose by drops (leaks) OR latency (queues age out your health). "
                 "Cover every kind, with throughput.", 24, yy + 6, F_S, MUTED)

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
            # coach: everything worth fixing, not just the top line
            text("COACH", 360, 56, F_S, MUTED)
            yy2 = 76
            for h in coach:
                for j, ln in enumerate(wrap(h.text, GW - 380, F_S)):
                    text(("- " if j == 0 else "  ") + ln, 360, yy2, F_S, coach_c[h.level])
                    yy2 += 16
                for ln in wrap(h.fix, GW - 396, F_S) if h.fix else []:
                    text("    -> " + ln, 360, yy2, F_S, AMBER)
                    yy2 += 16
                yy2 += 6

        # in-app code editor (toggle C): edit loadout.py, Ctrl+S to apply
        if code_mode:
            les_next = les_skip = les_start = None
            ov = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
            ov.fill((6, 10, 16, 246))
            screen.blit(ov, (0, 0))
            text("CODE — loadout.py   Ctrl+S apply · Ctrl+Z undo · click/scroll · Esc close",
                 16, 12, F_S, PHOS)
            if code_status["msg"]:
                ok = not code_status["msg"].startswith("error")
                text(code_status["msg"], 16, 34, F_S, PHOS if ok else DANGER)
            line_h, top = 16, 56
            avail = (WIN_H - top - 16) // line_h
            # mouse-wheel scroll, but always keep the caret line in view
            if code_buf.row < code_scroll:
                code_scroll = code_buf.row
            elif code_buf.row >= code_scroll + avail:
                code_scroll = code_buf.row - avail + 1
            code_scroll = max(0, min(code_scroll, max(0, len(code_buf.lines) - avail)))
            first = code_scroll
            syntax_c = {"kw": (130, 170, 255), "num": AMBER, "comment": MUTED}
            for i in range(first, min(len(code_buf.lines), first + avail)):
                y = top + (i - first) * line_h
                text(f"{i + 1:>3}", 16, y, F_S, MUTED)
                cx = 52
                for tok, kind in code_spans(code_buf.lines[i]):  # syntax highlighting
                    text(tok, cx, y, F_S, syntax_c.get(kind, INK))
                    cx += F_S.size(tok)[0]
                if i == code_buf.row:  # caret
                    cx = 52 + F_S.size(code_buf.lines[i][: code_buf.col])[0]
                    pygame.draw.line(screen, PHOS, (cx, y), (cx, y + 14), 1)

            # ---- Python lessons panel (right side of the editor) ----
            lx, lw = LESSON_X, WIN_W - LESSON_X - 16
            pygame.draw.line(screen, GRID, (lx - 14, 40), (lx - 14, WIN_H - 16), 1)
            if lessons.active and lessons.lesson is not None:
                lessons.check(world, editor)   # live-update the ✓ as the board changes
                le = lessons.lesson
                text(f"PYTHON LESSONS   {lessons.i + 1}/{len(lessons.script)}",
                     lx, 12, F_S, MUTED)
                text(le.title, lx, 38, F_M, PHOS)
                yy = 66
                for para in le.teach:
                    for ln in wrap(para, lw, F_S):
                        text(ln, lx, yy, F_S, INK)
                        yy += 16
                    yy += 5
                text("TASK", lx, yy, F_S, AMBER)
                yy += 18
                for ln in wrap(le.task, lw, F_S):
                    text(ln, lx, yy, F_S, INK)
                    yy += 16
                if le.concept:
                    yy += 6
                    text(f"concept: {le.concept}", lx, yy, F_S, MUTED)
                    yy += 22
                if le.check is not None:
                    text("done!" if lessons.passed else "try it, then Ctrl+S to run & check",
                         lx, yy, F_S, PHOS if lessons.passed else MUTED)
                les_skip = pygame.Rect(lx, WIN_H - 42, 108, 24)
                pygame.draw.rect(screen, MUTED, les_skip, 1, border_radius=4)
                text("Skip lessons", les_skip.x + 8, les_skip.y + 4, F_S, MUTED)
                if lessons.can_advance():
                    label = "Finish" if lessons.i == len(lessons.script) - 1 else "Next"
                    les_next = pygame.Rect(lx + lw - 96, WIN_H - 42, 96, 24)
                    pygame.draw.rect(screen, PHOS, les_next, border_radius=4)
                    text(f"{label}  >", les_next.x + 14, les_next.y + 4, F_S, PANEL2)
            else:
                text("PYTHON LESSONS", lx, 12, F_S, MUTED)
                text("A guided tour of the Python in loadout.py.", lx, 40, F_S, INK)
                les_start = pygame.Rect(lx, 74, 132, 26)
                pygame.draw.rect(screen, PHOS, les_start, border_radius=4)
                text("Start lessons", les_start.x + 12, les_start.y + 5, F_S, PANEL2)

        if not world.over:
            end_score["saved"] = False  # arm scoring for the next game-over

        if world.paused and not world.over and not code_mode:
            text("|| PAUSED — P resume · . step one tick", GW // 2 - 130, 36, F_M, AMBER)

        if world.over and not code_mode:
            if not end_score["saved"]:  # record the score once, persist the best
                end_score["score"] = world.score()
                end_score["best"] = save_highscore(HISCORE_PATH, end_score["score"])
                end_score["saved"] = True
            ov = pygame.Surface((GW, WIN_H), pygame.SRCALPHA)
            ov.fill((8, 14, 22, 210))
            screen.blit(ov, (0, 0))
            msg = "PIPELINE HELD" if world.won else "PIPELINE OVERWHELMED"
            text(msg, GW // 2 - 110, 56, F_L, PHOS if world.won else DANGER)
            text(f"score {end_score['score']}    best {end_score['best']}",
                 GW // 2 - 90, 90, F_M, INK)
            handled = sum(s.handled for s in world.stats.values())
            leaked = sum(s.leaked for s in world.stats.values())
            text(f"waves cleared {world.wave_idx}   ·   handled {handled}   ·   "
                 f"leaked {leaked}", GW // 2 - 150, 112, F_S, MUTED)
            if not world.won:
                # incident post-mortem: what failed, on which kinds and nodes
                deb = summarize_failure(world)
                text(deb.cause, 40, 138, F_S, INK)
                text("WHERE IT BROKE", 40, 164, F_S, MUTED)
                for i, ln in enumerate(deb.lines[:6]):
                    text("- " + ln, 48, 184 + i * 18, F_S, DANGER)
            text("Press R to retry, or edit loadout.py and F5.",
                 GW // 2 - 150, WIN_H - 80, F_S, INK)

        # guided tutorial: a card docked at the BOTTOM so it never covers the board
        # (nodes/turrets sit up top) — you can read the step and act at the same time.
        tut_next = tut_skip = None
        if tutorial.active and tutorial.step is not None:
            step = tutorial.step
            bw = min(720, GW - 24)
            line_h = F_S.get_height() + 5
            bh = 52 + len(step.body) * line_h + 40
            bx, by = (GW - bw) // 2, WIN_H - bh - 14
            # a soft backdrop just behind the card keeps the board fully visible above it
            backdrop = pygame.Surface((bw + 16, bh + 12), pygame.SRCALPHA)
            backdrop.fill((6, 10, 16, 220))
            screen.blit(backdrop, (bx - 8, by - 6))
            pygame.draw.rect(screen, PANEL2, (bx, by, bw, bh), border_radius=8)
            pygame.draw.rect(screen, PHOS, (bx, by, bw, bh), 2, border_radius=8)
            idx = tutorial.script.index(step) + 1
            text(f"Step {idx}/{len(tutorial.script)}", bx + bw - 92, by + 12, F_S, MUTED)
            text(step.title, bx + 18, by + 12, F_M, PHOS)
            ty = by + 44
            for ln in step.body:
                text(ln, bx + 18, ty, F_S, INK)
                ty += line_h
            # buttons: Skip always; Next/Start only when the step is a manual one
            tut_skip = pygame.Rect(bx + 18, by + bh - 34, 70, 24)
            pygame.draw.rect(screen, MUTED, tut_skip, 1, border_radius=4)
            text("Skip", tut_skip.x + 16, tut_skip.y + 4, F_S, MUTED)
            if step.is_manual:
                label = step.button
                tut_next = pygame.Rect(bx + bw - 130, by + bh - 34, 112, 24)
                pygame.draw.rect(screen, PHOS, tut_next, border_radius=4)
                text(f"{label}  >", tut_next.x + 14, tut_next.y + 4, F_S, PANEL2)
            else:
                text("(do the action above to continue)", bx + bw - 280, by + bh - 30,
                     F_S, AMBER)

        pygame.display.flip()
        await asyncio.sleep(0)  # yield to the browser event loop (no-op cost on desktop)

    pygame.quit()


def run() -> None:  # pragma: no cover - thin sync wrapper around the async loop
    """Synchronous entry point for the desktop build and the console script."""
    asyncio.run(main())
