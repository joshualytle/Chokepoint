# Contributing to Chokepoint

Thanks for your interest! Chokepoint is a small, deliberately readable codebase —
it's a game *and* a teaching tool for people learning Python. Contributions that
keep it clear and well-tested are very welcome.

## Getting set up

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make check                       # ruff + mypy + pytest — must be green
python -m chokepoint             # run the game
```

No `make`? Run the three directly:

```bash
ruff check src tests && mypy src && pytest -q
```

For the native-web app, `python serve_native.py` (serves `web/` on :8001).

## Ground rules (please keep these true)

These are what keep the codebase testable and approachable:

1. **The logic core imports no pygame and never touches a display.** Everything
   except `render.py` is pure and tested headless (`simulation.py`, `packets.py`,
   `arsenal.py`, `maps.py`, `gates.py`, `limiter.py`, `parsers.py`, `metrics.py`,
   `hints.py`, `editor.py`, `tutorial.py`, …). UI-only code lives in `render.py`.
2. **Fire rate is static.** Modules may change damage/range/coverage, never
   `fire_rate` — there's a test asserting this. Keep it passing.
3. **Every behavior change gets a test** in `tests/`.
4. **Content is drop-in.** Add guns/modules via `@register_gun` / `register_module`
   so they flow into tooltips, unlocks, and loadouts automatically. Devices
   (gates/limiters/parsers) follow the same pure-data pattern.
5. **`llm_assist` stays optional, stdlib-only, localhost-only,** and never raises
   into the game loop.

## Style

- Formatting/linting is [ruff](https://docs.astral.sh/ruff/); types are
  [mypy](https://mypy-lang.org/). Line length is 100.
- Favor **clear over clever** — this is a learning codebase. When a Python idiom
  first appears (decorators, `frozenset`, comprehensions, `key=` functions,
  threading), a one-line comment explaining it is welcome.
- Name the pipeline parallel where it helps: turrets are typed consumers, a
  coverage gap is an unhandled event type, a saturated queue is backpressure.
- Small, reviewable changes. Say what each does and why.

## Where things live

See the "Project layout" section of [README.md](README.md) and the architecture
notes in [CLAUDE.md](CLAUDE.md). In short: touch the pure modules for behavior
(with tests), then `render.py` for UI — and keep them separable.

## Submitting a change

1. Branch off `main` (e.g. `feature/my-thing` or `fix/my-thing`).
2. Make the change with tests; run `make check` until it's green.
3. Write a clear commit message: a short imperative summary, then a body
   explaining the *why* if it isn't obvious.
4. Open a pull request describing what changed and how you verified it.

## AI-assisted contributions

AI-assisted work is welcome — just be transparent about it. If a tool co-authored
a commit, keep the `Co-Authored-By:` trailer so the history is honest. You are
still responsible for reviewing and standing behind everything you submit.

## Reporting issues

Open a GitHub issue with what you expected, what happened, and steps to
reproduce (OS, Python version, and desktop vs. browser build help a lot).
