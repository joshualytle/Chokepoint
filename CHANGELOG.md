# Changelog

All notable changes to Chokepoint are noted here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this project is pre-1.0, so
minor versions may still move quickly.

## [Unreleased]

### Added
- **Native-web build** (`web/`): the pure Python core runs in the browser via
  Pyodide with an HTML/canvas UI and a CodeMirror editor — no install for
  players. Player `loadout.py` runs in a restricted sandbox (`safety.py`).
- **Flow devices**: gates (typed routers), quelimiters (rate limiters), and
  parsers (decode `raw` alerts) — placeable from the palette or in code — plus
  the `ingest` difficulty that streams raw alerts.
- **Training platform**: a guided tutorial and a library of hands-on
  walkthroughs (spill/overflow, gates, parsers, modules), in-editor Python
  lessons, a teaching coach that explains *why* + the fix, contextual "what is
  this?" help, and a glossary.
- **Inspector**: click any board object to see its stats *and* the equivalent
  `build_loadout` Python; swap a turret's gun or equip modules inline.
- **Flow animation**: waiting packets age toward red and pulse as latency
  builds, turrets show a processing beam/burst, and edges show flow direction.
- **Achievements**, per-walkthrough completion tracking, a per-level pause with
  an optional endless mode, undo, and browser persistence of your build.

### Changed
- Turrets are placed and dragged freely (with collision boundaries so they can't
  stack); the coach pins important warnings so advice doesn't vanish.
- Retired the older pygame-in-browser (pygbag) build in favor of the native-web
  app.

### Fixed
- Turrets now fire at their documented `fire_rate`: the cooldown carries the
  part of a tick it overshot instead of discarding it (guns ran 2-6% slow).
- Runaway loadout code (a huge `for` loop, `range(10**15)`, `10 ** 10 ** 10`) is
  stopped with "your code ran too long" instead of freezing the browser tab.
- A refused edge/node removal no longer reorders a fork's branches (which
  changed where ungated packets and gate routes went).
- A quelimiter with `release_rate` below 1.0 now releases packets instead of
  holding them forever (its token cap never reached one whole token).
- Editing the build no longer resets turret cooldowns, so clicking can't push a
  turret past its static fire rate.
- A decoded `raw` alert now counts as spawned under its real kind (in both the
  stats table and telemetry), so per-kind spawned/handled/leaked add up.
- The credit bank refuses negative amounts, so a device with a negative cost
  can no longer mint credits or drive the balance below zero on refund.
- The loadout sandbox now blocks underscore and introspection attributes
  (`gi_frame`, `f_back`, `co_consts` …), `str.format`, and underscore or `*`
  names in from-imports, which could reach the real builtins. f-strings still
  work.
- Loadout code gets a read-only `MODULE_LIBRARY`, so it can't empty the shared
  registry.
- A loadout that fails part-way on the web (a bad device builder, a missing
  `return`) now reports the error and leaves credits and the build untouched.
- Exported loadouts (`from __future__ import annotations`) load on the web, and
  `try`/`except IndexError:` and friends work in loadout code.
- Editing the build no longer zeroes a quelimiter's earned release credit, so
  clicking can't stall a slow limiter's releases.
- The web app falls back to the default difficulty for an unknown name and
  reports the one actually played, as it already did for an unknown map.
- Importing `MODULE_LIBRARY` from `chokepoint.arsenal` in loadout code now gives
  a read-only view too, so it can't empty the shared registry that way either.
- The shipped example `loadout.py` uses absolute imports, so it can be pasted
  into the web editor (the sandbox refuses relative imports).
- Packets stranded by removing a node mid-wave now count as leaked in the
  per-kind stats and telemetry (not toward game over), so the books balance.
- Running a lesson's code on desktop now refunds gates and limiters (and
  modules) along with turrets, so swapping builds no longer loses credits.

### Notes
- The desktop build (`python -m chokepoint`) is unchanged and remains the
  reference experience.

[Unreleased]: https://github.com/joshualytle/Chokepoint/commits/main
