"""Contract tests for the web bridge (web/webgame.py).

The bridge is pure Python (no pygame, no Pyodide needed at import time), so we can
exercise its JSON surface headlessly. These guard the shapes the JS UI relies on
and the placement/economy/resume behaviors that don't live in the pure core.
"""

import json

import webgame as wg


def fresh(map_name="trunk", difficulty="easy"):
    wg.new_game(map_name, difficulty)


def snap():
    return json.loads(wg.snapshot_json())


# ---- lifecycle + snapshot shape ---- #
def test_new_game_lists_maps_and_difficulties():
    meta = json.loads(wg.new_game("trunk", "easy"))
    assert meta["ok"] and "trunk" in meta["maps"] and "easy" in meta["difficulties"]


def test_snapshot_has_the_keys_the_ui_draws():
    fresh()
    s = snap()
    for key in ("wave", "health", "leaks", "credits", "nodes", "edges", "packets",
                "turrets", "gates", "limiters", "parsers", "stats", "coach",
                "upcoming", "intermission", "coverage_gaps"):
        assert key in s, f"missing snapshot key: {key}"


def test_palette_has_guns_devices_modules():
    fresh()
    pal = json.loads(wg.palette_json())
    assert pal["guns"] and any(g["name"] == "sieve" for g in pal["guns"])
    assert {d["kind"] for d in pal["devices"]} == {"gate", "limiter"}
    assert isinstance(pal["modules"], list)


# ---- placement: snap to line, no overlap, free drag ---- #
def test_place_snaps_to_line_and_avoids_overlap():
    fresh()
    wg.select_gun("sieve")
    assert json.loads(wg.place_at(370, 180))["ok"]
    assert json.loads(wg.place_at(371, 181))["ok"]     # aimed at the same spot
    ts = snap()["turrets"]
    assert len(ts) == 2
    d = ((ts[0]["x"] - ts[1]["x"]) ** 2 + (ts[0]["y"] - ts[1]["y"]) ** 2) ** 0.5
    assert d >= 29.0, f"turrets overlap (separation {d:.1f})"


def test_move_at_is_free_positioning():
    fresh()
    wg.select_gun("sieve")
    wg.place_at(370, 180)
    t = snap()["turrets"][0]
    wg.move_at(t["x"], t["y"], 300, 500)
    moved = snap()["turrets"][0]
    assert abs(moved["x"] - 300) < 40 and abs(moved["y"] - 500) < 40


def test_place_requires_a_selection():
    fresh()
    assert json.loads(wg.place_at(370, 180))["ok"] is False


# ---- inspector: identity + code + edits ---- #
def test_inspect_turret_returns_code_and_options():
    fresh()
    wg.select_gun("sieve")
    wg.place_at(370, 180)
    t = snap()["turrets"][0]
    r = json.loads(wg.inspect_at(t["x"], t["y"]))
    assert r["kind"] == "turret"
    assert "make_gun(\"sieve\")" in r["code"]
    assert r["guns"] and r["mods"] is not None


def test_swap_gun_from_inspector():
    fresh()
    wg.select_gun("sieve")
    wg.place_at(370, 180)
    t = snap()["turrets"][0]
    alt = next(g for g in json.loads(wg.inspect_at(t["x"], t["y"]))["guns"] if not g["current"])
    assert json.loads(wg.set_gun_at(t["x"], t["y"], alt["name"]))["ok"]
    assert snap()["turrets"][0]["gun"] == alt["name"]


def test_inspect_empty_space_is_none():
    fresh()
    assert json.loads(wg.inspect_at(5, 600))["kind"] is None


# ---- undo ---- #
def test_undo_reverses_a_placement():
    fresh()
    wg.select_gun("sieve")
    wg.place_at(370, 180)
    assert len(snap()["turrets"]) == 1
    assert json.loads(wg.undo())["ok"]
    assert len(snap()["turrets"]) == 0


# ---- resume: start at a later wave with earned budget ---- #
def test_start_at_wave_grants_budget_and_advances():
    fresh()
    base = snap()["credits"]
    wg.start_at_wave(4)
    s = snap()
    assert s["wave"] == 4
    assert s["credits"] > base          # accumulated wave income
    assert len(s["unlocked"]) >= 1


# ---- loadout code: deploy + error line reporting ---- #
def test_load_loadout_deploys_and_reports_error_line():
    fresh()
    ok = json.loads(wg.load_loadout(
        "def build_loadout(unlocked, slots):\n"
        "    return [Turret(*slots[0], gun=make_gun('sieve'))]\n"))
    assert ok["ok"] and ok["turrets"] == 1
    bad = json.loads(wg.load_loadout(
        "def build_loadout(unlocked, slots):\n"
        "    return [Turret(*slots[999], gun=make_gun('sieve'))]\n"))
    assert bad["ok"] is False and bad["line"] == 2


# ---- training surfaces ---- #
def test_walkthroughs_and_tutorial_state():
    fresh()
    wts = json.loads(wg.walkthroughs_json())
    ids = {w["id"] for w in wts}
    assert {"basics", "overflow", "routing", "ingest", "upgrades"} <= ids
    assert json.loads(wg.start_walkthrough("routing"))["ok"]
    assert json.loads(wg.tutorial_state())["active"]
