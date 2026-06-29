# HANDOFF — Chokepoint → browser build

Kickoff for a fresh session. Start with:
**"Read HANDOFF.md and CLAUDE.md, verify the build (`ruff check src tests && mypy
src && pytest -q`), then plan the browser port."**

## The goal for this session

Make Chokepoint **playable in a web browser** so it can be hosted as static files
on a desktop. Today it's a native pygame desktop app (`python -m chokepoint`).
The desktop build must keep working; the web build is an additional target.

## Recommended approach: pygbag (pygame → WebAssembly)

[pygbag](https://pypi.org/project/pygbag/) compiles a pygame app to WASM
(Pyodide) and emits static files (`index.html` + `.apk`/wasm) that any static
server can host — exactly the "host on my desktop" ask. It reuses ~all our code;
the only real change is making the render loop async. **Do not rewrite the game
in JS** — that throws away `render.py` and gains nothing here.

### Steps
1. `pip install pygbag` (add to an optional `[web]` extra in `pyproject.toml`).
2. **Async main loop.** pygbag requires `async def main()` and a
   `await asyncio.sleep(0)` once per frame (yields to the browser event loop).
   Convert `render.main()` to `async def main()`, add the `await` in the
   `while running:` loop, and have both `__main__.py` and a new root `main.py`
   (pygbag's entrypoint) call `asyncio.run(main())`. `asyncio.run` works on
   desktop too, so this keeps one code path.
3. Build/test locally: `python -m pygbag main.py` serves at
   http://localhost:8000 — open it to playtest in a browser.
4. Host: ship `build/web/` and serve it (`python -m http.server` from that dir,
   or any static host) on the desktop.

### Known gotchas to handle (all in `render.py` / entry, not the pure core)
- **pygame-ce**: pygbag bundles pygame-ce, not classic pygame. Our APIs are
  standard (draw, font, events) and should port cleanly; verify fonts —
  `SysFont("menlo,consolas,…")` may fall back to a bundled default in WASM.
- **Networking / `llm_assist`**: the browser sandbox blocks raw sockets, so the
  localhost-LLM `L` feature can't reach a model — it already degrades to a
  friendly message, but see threads below.
- **Threads**: `ask_llm` spawns `threading.Thread`; Pyodide has no real threads.
  Guard it: detect web (`sys.platform == "emscripten"`) and skip the thread (or
  wrap the start in try/except) so `L` is a graceful no-op in browser.
- **File I/O**: the in-app code editor (`S` save / `F5` reload of `loadout.py`)
  and the high-score file write to Pyodide's virtual FS. Within a session
  `importlib.reload(loadout_mod)` should work; **persistence across page reloads**
  needs pygbag's IndexedDB mount (or fall back to `localStorage`). Decide whether
  web save/persistence matters for v1 — it's fine to ship without it and note it.
- **Blocking calls**: nothing should block the frame; the per-frame
  `await asyncio.sleep(0)` is what keeps the page responsive.

### Suggested phasing
1. Async-loop refactor + `main.py`; confirm desktop still runs and `make check`
   stays green (the port shouldn't touch the tested pure modules at all).
2. First pygbag build; get it rendering and playable in a local browser.
3. Web guards (threads/LLM no-op), font check, then a hostable `build/web/`.
4. Optional: persistence (IndexedDB) for saved loadouts/high score.

## Current state — VERIFIED (desktop)

- `python -m chokepoint` launches; **ruff clean, mypy clean, 137 tests passing.**
- Everything but `render.py` is pygame-free and tested headless — so the port
  only risks `render.py` + entrypoints; the simulation/economy/gates/limiter/
  metrics/hints/editor/maps logic is untouched and stays green.
- Feature-complete desktop game: placement editor (E), build-mode topology
  editing (T), in-app code editor (C), gates, quelimiters, telemetry + coach,
  difficulties (calm/easy/adaptive/overkill), sandbox (K), fast-forward (F),
  scoring, walkthrough. Press `H` in-game for all controls.

## Repo / branch state

- All work is on `feature/player-topology`, pushed. **Merge that PR and delete
  the branch**, then branch fresh for the web port (e.g. `feature/web-build`).
- `gh` CLI token is invalid (HTTP 401) — PRs are opened/merged manually via the
  GitHub UI. Commits use the no-reply email
  `287242675+joshualytle@users.noreply.github.com` (GitHub blocks pushes that
  expose the real email). Always `git push` after committing on a PR'd branch.

## Guardrails — keep these true

1. Pure modules (everything but `render.py`) import no pygame, no display, no
   network. The port must not break this — keep web-specific shims in
   `render.py`/entrypoints.
2. Fire rate is static; modules never change it (there's a test).
3. Behavior changes get tests in `tests/`.
4. Guns/modules/maps/gates/limiters are drop-in via the registries / `build_graph`.
5. `llm_assist` stays optional, stdlib-only, localhost-only, never raises into
   the loop — and becomes a graceful no-op on web.

## Suggested first prompt

> "Plan the pygbag port: refactor render.main() to an async loop behind a new
> main.py, keep `python -m chokepoint` working and `make check` green, then do a
> first local browser build and tell me how to host build/web on my desktop."
