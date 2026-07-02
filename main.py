"""pygbag entry point for the browser (WASM) build.

pygbag looks for a top-level ``main.py`` and runs its ``main()`` coroutine on
the browser event loop. Build/serve locally with::

    python -m pygbag main.py     # serves http://localhost:8000

then ship the generated ``build/web/`` to any static host. The desktop build is
unchanged — keep using ``python -m chokepoint``.
"""

import asyncio
import sys
from pathlib import Path

# The package lives under src/ (src-layout). On the desktop it's pip-installed,
# but the browser build runs from the bundled tree, so put src/ on the path.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from chokepoint.render import main  # noqa: E402  (after sys.path setup)


async def _run() -> None:
    """Run the game; on the web, paint the outcome on-canvas (no devtools needed).

    If ``main()`` raises or returns, pygbag otherwise just blanks to grey with no
    clue why — especially on mobile. This draws the traceback (or an "ended"
    notice) onto the existing surface so the failure is readable on any device.
    """
    import pygame

    try:
        await main()
        message, bg = "Game loop ended (window closed).", (10, 22, 34)
    except Exception:
        import traceback

        message, bg = traceback.format_exc(), (28, 4, 6)

    surface = pygame.display.get_surface()
    if surface is None:  # no display (e.g. headless desktop) — re-raise for the console
        if bg == (28, 4, 6):
            raise
        return
    pygame.font.init()
    glyph = pygame.font.Font(None, 20)
    lines = message.splitlines()[-30:]
    while True:
        surface.fill(bg)
        for i, line in enumerate(lines):
            surface.blit(glyph.render(line[:118], True, (240, 200, 200)), (8, 8 + i * 20))
        pygame.display.flip()
        await asyncio.sleep(0.25)


if __name__ == "__main__":
    asyncio.run(_run())
