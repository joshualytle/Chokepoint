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

if __name__ == "__main__":
    asyncio.run(main())
