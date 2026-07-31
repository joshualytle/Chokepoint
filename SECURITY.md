# Security Policy

Chokepoint is a single-player learning game. It runs entirely on your machine
(desktop) or in your own browser tab (the web build), has **no backend**, and
opens **no network connections** — with one optional, off-by-default exception:
the desktop `L` key can ask a **local** LLM for hints, and that only ever talks
to `localhost`. Player-authored `loadout.py` in the web build is executed inside
a restricted sandbox (`src/chokepoint/safety.py`: an AST allowlist plus
restricted builtins) so shared code cannot import arbitrary modules or reach the
network/DOM.

## Supported versions

The project is pre-1.0. Security fixes are applied to the `main` branch; please
test against the latest `main`.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead:

- Open a private [GitHub Security Advisory](https://github.com/joshualytle/Chokepoint/security/advisories/new), or
- Contact the maintainer, [@joshualytle](https://github.com/joshualytle), privately.

Include what you found, how to reproduce it, and the potential impact. You can
expect an acknowledgement, and we'll work with you on a fix and coordinated
disclosure. Reports about the sandbox (`safety.py`) — any way to escape the AST
allowlist or restricted builtins — are especially welcome.

Thank you for helping keep the project and its users safe.
