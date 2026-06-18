"""Optional local-LLM helper for diagnosing your loadout.

If you run a local model (Ollama, LM Studio, llama.cpp, or anything exposing an
OpenAI-compatible or Ollama API on localhost), the game can hand it the current
game state and your question and show its advice. Entirely optional: with no
local LLM running, everything degrades to a friendly message and the game is
unaffected.

Configuration via environment variables (no secrets in code):
  FD_LLM_URL    default http://localhost:11434/api/generate   (Ollama)
                for OpenAI-compatible servers, point at /v1/chat/completions
  FD_LLM_MODEL  default "llama3.1"

Stdlib only — no extra dependencies, and it only ever talks to your localhost.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("FD_LLM_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.environ.get("FD_LLM_MODEL", "llama3.1")

SYSTEM = (
    "You are a terse assistant inside a tower-defense game that simulates a "
    "security alert pipeline. Turrets are typed consumers; packets are typed "
    "alerts; a turret only processes kinds its gun accepts. Diagnose coverage "
    "gaps and throughput shortfalls in plain language, max ~6 lines."
)


def available(url: str = DEFAULT_URL, timeout: float = 0.6) -> bool:
    """Quick reachability check. Returns False fast if nothing is listening."""
    base = url.split("/api/")[0].split("/v1/")[0]
    try:
        urllib.request.urlopen(base, timeout=timeout)  # noqa: S310 - localhost only
        return True
    except urllib.error.HTTPError:
        return True  # server answered (even a 404) => it's up
    except Exception:
        return False


def _is_openai_style(url: str) -> bool:
    return "/v1/" in url or url.rstrip("/").endswith("chat/completions")


def diagnose(
    context: str,
    question: str,
    url: str = DEFAULT_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 20.0,
) -> str:
    """Ask the local LLM for help. Never raises — returns advice or a fallback."""
    prompt = f"{SYSTEM}\n\nGAME STATE:\n{context}\n\nQUESTION: {question}"
    if _is_openai_style(url):
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"GAME STATE:\n{context}\n\n{question}"},
            ],
            "stream": False,
        }
    else:
        payload = {"model": model, "prompt": prompt, "stream": False}

    try:
        req = urllib.request.Request(  # noqa: S310 - localhost only
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - localhost
            data = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - any failure -> friendly fallback
        return (
            f"Local LLM unavailable ({exc}).\n"
            "Start Ollama (`ollama run llama3.1`) or set FD_LLM_URL / FD_LLM_MODEL. "
            "The game runs fine without it."
        )

    # Ollama returns {"response": ...}; OpenAI-style returns {"choices":[...]}.
    if "response" in data:
        return str(data["response"]).strip() or "(empty response)"
    try:
        return str(data["choices"][0]["message"]["content"]).strip() or "(empty response)"
    except (KeyError, IndexError, TypeError):
        return "(unrecognized LLM response shape)"


def state_summary(world) -> str:  # noqa: ANN001 - duck-typed World to avoid import cycle
    """Build a compact context string from a World for the LLM."""
    lines = [
        f"map={world.map.name} wave={world.level} leaks={world.leaks}",
        f"coverage={sorted(world.coverage())}",
        f"coverage_gaps={sorted(world.coverage_gaps())}",
    ]
    for t in world.turrets:
        lines.append(
            f"{t.id} gun={t.gun.name} accepts={sorted(t.accepts())} "
            f"range={t.range():.0f} dps={t.dps():.1f}"
        )
    for k, s in world.stats.items():
        if s.spawned:
            lines.append(f"{k}: spawned={s.spawned} handled={s.handled} leaked={s.leaked}")
    return "\n".join(lines)
