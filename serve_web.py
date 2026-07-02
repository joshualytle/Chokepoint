"""Serve the pygbag build (``build/web``) for local + LAN play-testing.

    python serve_web.py            # http://localhost:8000  and  http://<lan-ip>:8000
    python serve_web.py 9000       # pick a port

Why not pygbag's own test server? In pygbag 0.9.3 it sends an invalid
``Cross-Origin-Opener-Policy: cross-origin`` plus ``Cross-Origin-Embedder-Policy:
require-corp``. That combination is *not* cross-origin isolated, yet require-corp
still blocks the runtime files the loader pulls from the pygame-web CDN (which
send no Cross-Origin-Resource-Policy header) — so the page hangs at "downloading".

Over plain HTTP to a LAN IP the origin isn't a "secure context", so
SharedArrayBuffer is unavailable no matter what — pygbag runs single-threaded
anyway. So we drop COEP entirely (CDN loads freely) and just fix the .wasm
mimetype, which is all a single-threaded pygbag build needs.
"""

from __future__ import annotations

import sys
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build" / "web"
CDN_BASE = "https://pygame-web.github.io/cdn/"


# pygame-web's runtime aborts with "unsupported device pixel ratio" on fractional
# ratios (Windows display scaling -> 1.25/1.5, phones -> 2.6/3). Snapping the
# ratio to a supported integer (2 on any hi-DPI display, else 1) BEFORE the
# runtime reads it both avoids the abort and lets it render at 2x and downscale,
# which is crisp on a scaled display (forcing 1 made text soft). Injected as the
# first tag so it runs before pygbag's deferred loader.
DPR_SHIM = (
    b"<script>try{var _r=window.devicePixelRatio||1,_s=_r>1?2:1;"
    b"Object.defineProperty(window,'devicePixelRatio',"
    b"{configurable:true,get:function(){return _s;}});}catch(e){}</script>\n"
)


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = DPR_SHIM + (BUILD_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/cdn/"):
            self._serve_cdn(self.path[len("/cdn/") :].split("?", 1)[0])
            return
        super().do_GET()

    def _serve_cdn(self, rel: str) -> None:
        """Proxy (and cache) pygbag's package files from the pygame-web CDN.

        pygbag resolves runtime wheels (pygame-ce, etc.) against our origin under
        /cdn/, expecting the dev server to proxy them. We fetch once, cache under
        build/web/cdn/, and serve same-origin thereafter (fast + works offline).
        """
        cached = BUILD_DIR / "cdn" / rel
        try:
            if not cached.is_file():
                with urllib.request.urlopen(CDN_BASE + rel, timeout=60) as up:  # noqa: S310
                    data = up.read()
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
            data = cached.read_bytes()
        except Exception as exc:  # noqa: BLE001 - report any proxy failure to the loader
            self.send_error(502, f"CDN proxy failed for {rel}: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(cached)))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self) -> None:
        # COOP is harmless and lets isolation kick in *if* served over https;
        # we deliberately omit COEP so cross-origin CDN runtime files aren't blocked.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if not BUILD_DIR.is_dir():
        sys.exit(f"No build found at {BUILD_DIR}. Run:  python -m pygbag --build main.py")
    handler = partial(Handler, directory=str(BUILD_DIR))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)  # noqa: S104 - LAN play-testing is the goal
    print(f"Serving {BUILD_DIR} on http://localhost:{port}  (LAN: http://<this-ip>:{port})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
