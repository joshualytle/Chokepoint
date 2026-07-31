<!-- Thanks for contributing! Keep changes small and reviewable. -->

## What & why

<!-- What does this change, and why? Link any related issue (e.g. Closes #12). -->

## How I verified it

<!-- Commands you ran / what you tested. -->

- [ ] `ruff check src tests` passes
- [ ] `mypy src` passes
- [ ] `pytest -q` passes
- [ ] Added/updated a test for any behavior change (see the invariants below)

## Checklist

- [ ] The logic core stays pygame-free and headless-testable (only `render.py`
      touches a display)
- [ ] Fire rate stays static (modules may change damage/range/coverage, never
      `fire_rate`)
- [ ] New guns/modules are registered via `@register_gun` / `register_module`
- [ ] If a tool co-authored a commit, the `Co-Authored-By:` trailer is kept
