"""Serve the web-native (Pyodide) front end in ``web/`` for local + LAN testing.

    python serve_native.py            # http://localhost:8001  and  http://<lan-ip>:8001

On startup it zips ``src/chokepoint`` into ``web/chokepoint.zip`` so Pyodide can
unpack and import the game core in the browser — re-run this after changing the
Python core to refresh the bundle. Pyodide itself loads from its own CDN, so the
page needs internet on first load.
"""

from __future__ import annotations

import sys
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
WEB = ROOT / "web"
PKG = ROOT / "src" / "chokepoint"


def build_package() -> Path:
    """Zip the pure Python game core (the .py files only) for Pyodide."""
    out = WEB / "chokepoint.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PKG.rglob("*.py")):
            z.write(path, path.relative_to(ROOT / "src"))   # arcname: chokepoint/xxx.py
    return out


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".py": "text/x-python",
        ".wasm": "application/wasm",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")   # always serve the fresh bundle
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    zp = build_package()
    print(f"packaged core -> {zp} ({zp.stat().st_size} bytes)")
    handler = partial(Handler, directory=str(WEB))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)  # noqa: S104 - LAN testing is the goal
    print(f"Serving {WEB} on http://localhost:{port}  (LAN: http://<this-ip>:{port})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
