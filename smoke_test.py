#!/usr/bin/env python3
"""Lightweight smoke tests run during Docker build."""

import sys


def test_imports():
    import availableraids  # noqa: F401
    import raid  # noqa: F401
    print("OK: imports")


def test_wsgi_app():
    from raid import application
    status_holder = {}

    def start_response(status, headers):
        status_holder["status"] = status

    body = application({"QUERY_STRING": "", "PATH_INFO": "/", "SCRIPT_NAME": ""}, start_response)
    assert status_holder["status"] == "200 OK", f"unexpected status: {status_holder['status']}"
    html = b"".join(body).decode()
    assert "Raid Helper" in html, "missing title in response"
    print("OK: wsgi responds 200")


def test_type_effectiveness():
    from raid import calculate_effectiveness
    effective, double, resisting = calculate_effectiveness("dragon")
    assert "ice" in effective, "ice should be effective vs dragon"
    assert "dragon" in effective, "dragon should be effective vs dragon"
    print("OK: type effectiveness")


def test_format_difficulty():
    from raid import format_difficulty_label
    assert format_difficulty_label("5")[0] == "5+ trainers"
    assert format_difficulty_label("4.4")[0] == "5+ trainers"
    assert format_difficulty_label(None) == ("", None)
    assert format_difficulty_label("Shadow Tier 5 Raid") == ("", None)
    print("OK: format_difficulty_label")


def test_humanize_tier():
    from availableraids import humanize_tier
    assert "Shadow" in humanize_tier("RAID_LEVEL_5_SHADOW")
    assert "Mega" in humanize_tier("RAID_LEVEL_MEGA")
    print("OK: humanize_tier")


def test_display_name():
    from availableraids import display_name
    assert display_name("DIALGA") == "Dialga"
    assert display_name("LANDORUS_SHADOW_FORM") == "Shadow Landorus"
    assert display_name("DRAGONITE_MEGA") == "Mega Dragonite"
    assert display_name("CHARIZARD_MEGA_Y") == "Mega Charizard Y"
    assert display_name("ARCANINE_HISUIAN_FORM") == "Arcanine (Hisuian)"
    assert display_name("MEWTWO_A_FORM") == "Armored Mewtwo"
    print("OK: display_name")


def test_is_current_tier():
    from availableraids import is_current_tier
    assert is_current_tier("RAID_LEVEL_5")
    assert is_current_tier("RAID_LEVEL_MEGA")
    assert not is_current_tier("RAID_LEVEL_5_FUTURE")
    assert not is_current_tier("RAID_LEVEL_5_LEGACY")
    assert not is_current_tier("RAID_LEVEL_UNSET")
    # Max Battles are kept now: they are a different game mode, but the data
    # is good and they get their own section. They must still be *marked* as
    # a different mode -- see test_max_battles_are_separated().
    assert is_current_tier("RAID_LEVEL_5_MAX")
    assert not is_current_tier("RAID_LEVEL_5_MAX_FUTURE")
    assert not is_current_tier("RAID_LEVEL_5_MAX_LEGACY")
    print("OK: is_current_tier")


def test_icon_map_picks_the_richest_chunk():
    """Pokebattler moved the icon table and left a decoy behind.

    Before 2026-11-14 the scraper took the first chunk that matched
    `pokebattler-*`. When the table was split out into `pokemon-icons-*`, the
    old chunk still held ten stale Mega entries -- so the scrape "succeeded",
    returned 10 entries, and every boss on the site silently lost its picture.
    Nothing else broke, which is what made it hard to notice.
    """
    import availableraids

    def chunk(n, prefix="MON"):
        return "".join(f"{prefix}{i}:`pokemon_icon_{i:03d}_00.png`," for i in range(n))

    pages = {
        "https://www.pokebattler.com/raids": '<script src="/assets/index-AAA.js"></script>',
        "https://www.pokebattler.com/assets/index-AAA.js":
            'import"./assets/pokemon-icons-BBB.js";import"./assets/pokebattler-CCC.js";',
        # The real table, and the decoy that used to win.
        "https://www.pokebattler.com/assets/pokemon-icons-BBB.js": chunk(150),
        "https://www.pokebattler.com/assets/pokebattler-CCC.js": chunk(10, "OLD"),
    }

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeSession:
        def __init__(self):
            self.seen = []

        def get(self, url, timeout=None):
            self.seen.append(url)
            return FakeResponse(pages[url])

    session = FakeSession()
    icons = availableraids.fetch_icon_map(session)
    assert len(icons) == 150, f"took the wrong chunk: {len(icons)} entries"
    assert "MON7" in icons and "OLD7" not in icons

    # And the degenerate case: only the decoy exists. Still no crash, still a
    # usable (if poor) map -- icons are decoration and must never fail a run.
    pages["https://www.pokebattler.com/assets/index-AAA.js"] = \
        'import"./assets/pokebattler-CCC.js";'
    icons = availableraids.fetch_icon_map(FakeSession())
    assert len(icons) == 10

    # A page with no bundle at all yields an empty map, not an exception.
    pages["https://www.pokebattler.com/raids"] = "<html>no bundle here</html>"
    assert availableraids.fetch_icon_map(FakeSession()) == {}
    print("OK: icon map picks richest chunk")


def test_max_counter_table():
    """Pokebattler's precomputed Max table, walked and decoded.

    The chain is page -> useMaxData-* -> maxbattles-* -> max-bosses-compact-*,
    all hash-named, and the payload is a JS literal (backtick strings, bare
    keys), not JSON.
    """
    import availableraids

    table_js = (
        "var e={"
        "TOXTRICITY:{p:`TOXTRICITY`,t:`RAID_LEVEL_4_MAX`,g:`RAID_LEVEL_4_MAX`,"
        "w:[`POKEMON_TYPE_GROUND`],c:["
        "{p:`ETERNATUS_ETERNAMAX_FORM`,m1:`DRAGON_TAIL_FAST`,m2:`DYNAMAX_CANNON`,cat:`BEST`,e:`0.3000`},"
        "{p:`FLYGON`,m1:`SAND_ATTACK_FAST`,m2:`EARTHQUAKE`,cat:`BEST`,e:`1.3600`},"
        "{p:`EXCADRILL`,m1:`MUD_SHOT_FAST`,m2:`DRILL_RUN`,cat:`BEST`,e:`1.9000`}"
        "]}};export{e as default};"
    )
    pages = {
        "https://www.pokebattler.com/max/DYNAMAX_DIALGA": 'x"./assets/useMaxData-AAA.js"x',
        "https://www.pokebattler.com/assets/useMaxData-AAA.js": 'x"./maxbattles-BBB.js"x',
        "https://www.pokebattler.com/assets/maxbattles-BBB.js": 'x"./max-bosses-compact-CCC.js"x',
        "https://www.pokebattler.com/assets/max-bosses-compact-CCC.js": table_js,
    }

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeSession:
        def get(self, url, timeout=None):
            return FakeResponse(pages[url])

    table = availableraids.fetch_max_counters(FakeSession())
    assert set(table) == {"TOXTRICITY"}, table
    entry = table["TOXTRICITY"]
    # Eternamax is dropped, so the estimate is the best *obtainable* one.
    names = [c["pokemon"] for c in entry["counters"]]
    assert "Eternatus Eternamax Form" not in names, names
    assert names[0] == "Flygon", names
    assert entry["difficulty_raw"] == 1.36, entry

    # Attaching it: only Max Battles, and a miss leaves the entry alone.
    raids = [
        {"_slug": "TOXTRICITY", "max_battle": True, "difficulty": None},
        {"_slug": "DIALGA", "max_battle": True, "difficulty": None},   # not in table
        {"_slug": "TOXTRICITY", "max_battle": False, "difficulty": "9"},  # a raid
    ]
    availableraids.populate_max_counters(raids, table)
    assert raids[0]["difficulty"] == "2", raids[0]          # ceil(1.36)
    assert len(raids[0]["counters"]) == 2
    assert raids[1]["difficulty"] is None and "counters" not in raids[1]
    assert raids[2]["difficulty"] == "9", "a raid must not be touched"

    # A broken chain yields an empty table, never an exception.
    pages["https://www.pokebattler.com/max/DYNAMAX_DIALGA"] = "nothing here"
    assert availableraids.fetch_max_counters(FakeSession()) == {}
    print("OK: max counter table")


def test_saturated_estimators_are_dropped():
    """A pinned estimator is not a measurement and must not be published.

    Tier 6 bosses come back with three quarters of their counter list at
    96..99.5 -- and Gigantamax Machamp, the counter every guide names against
    fighting-weak Duraludon, dead last. Publishing "74+ trainers" off that is
    worse than publishing nothing.
    """
    from availableraids import _is_saturated

    assert _is_saturated([73.1, 76.6, 86.9, 96.9, 98.3, 99.0, 99.2, 99.4, 99.5])
    assert not _is_saturated([1.94, 5.13, 5.32, 5.48, 6.10, 7.58])
    assert not _is_saturated([1.09, 1.36, 1.59, 2.43, 2.46])
    assert _is_saturated([]), "no counters at all is not a usable estimate either"
    print("OK: saturated estimators dropped")


def test_icon_mirror_names_and_serving(tmp_dir=None):
    """Mirrored icons: flattened names, and no way to escape the directory."""
    import os
    import tempfile

    import availableraids
    import raid as raid_mod

    assert availableraids.mirrored_icon_name("pm/pm884.icon.png") == "pm_pm884.icon.png"
    assert availableraids.mirrored_icon_name("pokemon_icon_483_00.png") == "pokemon_icon_483_00.png"
    assert "/" not in availableraids.mirrored_icon_name("a/b/../c.png")

    directory = tempfile.mkdtemp()
    with open(os.path.join(directory, "pm_pm884.icon.png"), "wb") as fp:
        fp.write(b"\x89PNG\r\n\x1a\nstub")
    with open(os.path.join(directory, "secret.json"), "w") as fp:
        fp.write("{}")

    original = raid_mod.ICON_DIR
    raid_mod.ICON_DIR = directory
    try:
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(raid_mod.icon_response(start_response, "pm_pm884.icon.png"))
        assert captured["status"] == "200 OK"
        assert captured["headers"]["Content-Type"] == "image/png"
        assert body.startswith(b"\x89PNG")

        # Everything that is not exactly a mirrored name is a 404, including
        # the traversal shapes a proxy might pass through unnormalised.
        for bad in ("../secret.json", "..%2fsecret.json", "secret.json",
                    "sub/pm_pm884.icon.png", "pm_pm884.icon.png/../secret.json",
                    "", "nope.png"):
            raid_mod.icon_response(start_response, bad)
            assert captured["status"] == "404 Not Found", f"{bad!r} was not rejected"
    finally:
        raid_mod.ICON_DIR = original
    print("OK: icon mirror names and serving")


def test_max_battles_are_separated():
    """A Max Battle must never reach the raid list, and vice versa.

    RAID_LEVEL_5_MAX and _6_MAX both satisfy is_tier_five_or_higher(), so a
    tier-based filter would silently send people to a gym for a boss that
    only exists at a Power Spot.
    """
    import json
    import tempfile

    import raid

    rows = [
        {"pokemon": "Cresselia", "tier_raw": "RAID_LEVEL_5",
         "start_local": "Nov 10, 2026 6:00 AM", "end_local": "Nov 30, 2099 8:00 PM",
         "types": ["psychic"], "difficulty": "2", "max_battle": False},
        {"pokemon": "Dialga", "tier_raw": "RAID_LEVEL_5_MAX",
         "start_local": "Nov 10, 2026 5:00 AM", "end_local": "Nov 30, 2099 8:00 PM",
         "types": ["steel", "dragon"], "difficulty": None, "max_battle": True},
        # The standing Power-Spot rotation: no window at all.
        {"pokemon": "Sableye", "tier_raw": "RAID_LEVEL_3_MAX",
         "types": ["dark", "ghost"], "difficulty": None, "max_battle": True},
        # Written before the flag existed -- must still be detected by tier.
        {"pokemon": "Eternatus", "tier_raw": "RAID_LEVEL_6_MAX",
         "types": ["poison", "dragon"]},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
        json.dump(rows, fp)
        path = fp.name

    raids = raid.load_available_raids(path)
    maxes = raid.load_max_battles(path)

    assert [r["pokemon"] for r in raids] == ["Cresselia"], raids
    assert {r["pokemon"] for r in maxes} == {"Dialga", "Sableye", "Eternatus"}, maxes
    # No trainer count on a Max Battle: the simulator's number is wrong there.
    assert all(not r["difficulty"] for r in maxes)
    # An unscheduled Max Battle is permanent, not "starting soon".
    sableye = next(r for r in maxes if r["pokemon"] == "Sableye")
    assert sableye["status"] == "Always available", sableye
    assert sableye["state"] == "active"
    # Tier 6 is Gigantamax, not "Tier 6".
    eternatus = next(r for r in maxes if r["pokemon"] == "Eternatus")
    assert eternatus["tier"] == "Gigantamax", eternatus
    assert eternatus["tier_class"] == "tier-max"
    print("OK: max battles separated")


def test_build_raid_entries():
    """Boss rotation plus breakingNews window, no network involved."""
    from datetime import UTC, datetime, timedelta

    from availableraids import build_raid_entries

    def ms(delta):
        return int((datetime.now(UTC) + delta).timestamp() * 1000)

    blob = {
        "tiers": [
            {"tier": "RAID_LEVEL_5", "raids": [
                {"pokemonId": "DIALGA"},
                {"pokemonId": "PALKIA"},
                {"pokemonId": "GIRATINA"},
            ]},
            {"tier": "RAID_LEVEL_5_LEGACY", "raids": [{"pokemonId": "LUGIA"}]},
            {"tier": "RAID_LEVEL_UNSET", "raids": [{"pokemonId": "PIDGEY"}]},
        ],
        "breakingNews": [
            # running now
            {"pokemon": "DIALGA", "tier": "RAID_LEVEL_5",
             "startDate": ms(timedelta(days=-2)), "endDate": ms(timedelta(days=2))},
            # announced, inside the 3-day window
            {"pokemon": "PALKIA", "tier": "RAID_LEVEL_5",
             "startDate": ms(timedelta(days=2)), "endDate": ms(timedelta(days=5))},
            # over
            {"pokemon": "GIRATINA", "tier": "RAID_LEVEL_5",
             "startDate": ms(timedelta(days=-9)), "endDate": ms(timedelta(days=-2))},
            # a window for a boss that is not in the rotation
            {"pokemon": "LUGIA", "tier": "RAID_LEVEL_5",
             "startDate": ms(timedelta(days=-1)), "endDate": ms(timedelta(days=1))},
        ],
    }
    entries = build_raid_entries(blob, {"DIALGA": "pokemon_icon_483_00.png"})
    names = [entry["pokemon"] for entry in entries]
    assert names == ["Dialga", "Palkia"], names
    assert entries[0]["tier_raw"] == "RAID_LEVEL_5"
    assert entries[0]["image"].endswith("/pokemon_icon_483_00.png")
    # no icon in the table means no image, not a broken URL
    assert entries[1]["image"] is None
    assert entries[0]["start_utc"] and entries[0]["start_local"]
    print("OK: build_raid_entries")


def test_format_local():
    from zoneinfo import ZoneInfo

    from availableraids import format_local
    # 2026-10-14 13:00 UTC is 6 AM in California, as the site renders it
    assert format_local(1792587600000 - 7 * 24 * 3600 * 1000,
                        ZoneInfo("America/Los_Angeles")) == "Oct 14, 2026 6:00 AM"
    assert format_local(None, ZoneInfo("UTC")) is None
    print("OK: format_local")


def _call(path, query=""):
    from raid import application
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = application(
        {"QUERY_STRING": query, "PATH_INFO": path, "SCRIPT_NAME": ""}, start_response
    )
    captured["body"] = b"".join(body)
    return captured


def test_api_effectiveness():
    import json

    resp = _call("/api/effectiveness/ghost/dragon")
    assert resp["status"] == "200 OK", f"unexpected status: {resp['status']}"
    assert resp["headers"].get("Content-Type", "").startswith("application/json")
    data = json.loads(resp["body"])
    assert data["types"] == ["ghost", "dragon"]
    assert "ice" in data["effective_attackers"], "ice should hit dragon"
    assert "dragon" in data["effective_attackers"]
    assert data["search_string"], "expected a non-empty search string"

    # Unknown type → 400 with the list of valid types.
    bad = _call("/api/effectiveness/notatype")
    assert bad["status"] == "400 Bad Request", f"unexpected status: {bad['status']}"
    assert "types" in json.loads(bad["body"])
    print("OK: api effectiveness")


def test_api_raids():
    import json

    resp = _call("/api/raids")
    assert resp["status"] == "200 OK", f"unexpected status: {resp['status']}"
    assert resp["headers"].get("Content-Type", "").startswith("application/json")
    data = json.loads(resp["body"])
    for key in ("generated_at", "data_updated_at", "count", "raids"):
        assert key in data, f"missing {key} in raids payload"
    assert isinstance(data["raids"], list)
    assert data["count"] == len(data["raids"])

    # Bad state filter is rejected.
    bad = _call("/api/raids", query="state=bogus")
    assert bad["status"] == "400 Bad Request", f"unexpected status: {bad['status']}"
    print("OK: api raids")


def test_watchdog():
    from raid import application
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = application({"QUERY_STRING": "", "PATH_INFO": "/watchdog", "SCRIPT_NAME": ""}, start_response)
    assert captured["status"] == "200 OK", f"unexpected status: {captured['status']}"
    assert captured["headers"].get("Content-Type", "").startswith("text/plain"), \
        f"unexpected content-type: {captured['headers'].get('Content-Type')}"
    text = b"".join(body).decode()
    assert text.startswith("status: "), "missing status line"
    for key in ("name:", "version:", "time:", "raid_data:", "raid_data_age:", "active_raids:", "disk_space:"):
        assert key in text, f"missing {key} in watchdog body"
    print("OK: watchdog endpoint")


if __name__ == "__main__":
    tests = [test_imports, test_wsgi_app, test_type_effectiveness,
             test_format_difficulty, test_humanize_tier, test_display_name,
             test_is_current_tier, test_icon_map_picks_the_richest_chunk,
             test_max_counter_table, test_saturated_estimators_are_dropped,
             test_icon_mirror_names_and_serving, test_max_battles_are_separated,
             test_build_raid_entries, test_format_local,
             test_api_effectiveness, test_api_raids, test_watchdog]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
    sys.exit(failed)
