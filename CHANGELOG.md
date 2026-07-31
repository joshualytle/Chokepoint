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

### Notes
- The desktop build (`python -m chokepoint`) is unchanged and remains the
  reference experience.

[Unreleased]: https://github.com/joshualytle/Chokepoint/commits/main
