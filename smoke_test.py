#!/usr/bin/env python3
"""Lightweight smoke tests run during Docker build."""

import os
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


def _pvp_fixture(tmp_path):
    """A three-stage family plus an unrelated species, written as the real dump."""
    import json
    payload = {"pokemon": [
        {"id": "PAWNIARD", "slug": "pawniard", "name": "Pawniard",
         "atk": 154, "def": 114, "sta": 128, "types": ["dark", "steel"],
         "parent": None, "family": "FAMILY_PAWNIARD", "image": "/icons/a.png",
         "name_de": "Gladiantri"},
        {"id": "BISHARP", "slug": "bisharp", "name": "Bisharp",
         "atk": 232, "def": 176, "sta": 163, "types": ["dark", "steel"],
         "parent": "PAWNIARD", "family": "FAMILY_PAWNIARD", "image": "/icons/b.png"},
        {"id": "KINGAMBIT", "slug": "kingambit", "name": "Kingambit",
         "atk": 238, "def": 203, "sta": 225, "types": ["dark", "steel"],
         "parent": "BISHARP", "family": "FAMILY_PAWNIARD", "image": "/icons/c.png",
         "name_de": "Gladimperio"},
        {"id": "RATTATA", "slug": "rattata", "name": "Rattata",
         "atk": 103, "def": 70, "sta": 102, "types": ["normal"],
         "parent": None, "base": "RATTATA", "family": "FAMILY_RATTATA",
         "image": None, "name_de": "Rattfratz"},
        {"id": "RATTATA_ALOLA_FORM", "slug": "rattata-alola-form",
         "name": "Rattata (Alolan)", "atk": 103, "def": 70, "sta": 102,
         "types": ["dark", "normal"], "parent": None, "base": "RATTATA",
         "family": "FAMILY_RATTATA", "image": None, "name_de": "Alola-Rattfratz"},
        {"id": "RATICATE", "slug": "raticate", "name": "Raticate",
         "atk": 161, "def": 139, "sta": 146, "types": ["normal"],
         "parent": "RATTATA", "base": "RATICATE", "family": "FAMILY_RATTATA",
         "image": None, "name_de": "Rattikarl"},
        {"id": "RATICATE_ALOLA_FORM", "slug": "raticate-alola-form",
         "name": "Raticate (Alolan)", "atk": 135, "def": 154, "sta": 181,
         "types": ["dark", "normal"], "parent": "RATTATA", "base": "RATICATE",
         "family": "FAMILY_RATTATA", "image": None, "name_de": "Alola-Rattikarl"},
        {"id": "AERODACTYL", "slug": "aerodactyl", "name": "Aerodactyl",
         "atk": 221, "def": 159, "sta": 190, "types": ["rock", "flying"],
         "parent": None, "family": "FAMILY_AERODACTYL", "image": None,
         "name_de": "Aerodactyl"},
        {"id": "AERODACTYL_MEGA", "slug": "aerodactyl-mega", "name": "Mega Aerodactyl",
         "atk": 292, "def": 210, "sta": 190, "types": ["rock", "flying"],
         "parent": "AERODACTYL", "family": "FAMILY_AERODACTYL", "image": None,
         "name_de": "Mega-Aerodactyl"},
        {"id": "AZUMARILL", "slug": "azumarill", "name": "Azumarill",
         "atk": 112, "def": 152, "sta": 225, "types": ["water", "fairy"],
         "parent": "MARILL", "family": "FAMILY_MARILL", "image": None,
         "name_de": "Azumarill"},
    ]}
    path = tmp_path + "/pvp_pokemon.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_pvp_costume_forms_are_dropped():
    """Costumes are duplicates; genuine variants are not.

    "Charmander Fall 2019 Form" has Charmander's stats exactly, so it is the
    same row in every rank table and only makes the search box worse. The
    event year identifies those reliably -- and nothing else, which is the
    half worth testing: Alolan, Galarian, Hisuian, Therian, Unown letters
    and Paldean Tauros carry no year and have to survive.
    """
    from availableraids import build_pokemon_index
    blob = {"pokemon": [
        {"pokemonId": pid, "stats": {"baseAttack": 100, "baseDefense": 100,
                                     "baseStamina": 100},
         "type": "POKEMON_TYPE_FIRE", "pokedex": {"pokemonNum": 4}}
        for pid in (
            "CHARMANDER", "CHARMANDER_FALL_2019_FORM", "PIKACHU_GOTOUR_2024_A_02_FORM",
            "CORSOLA_SPRING_2026_FORM", "BEARTIC_WINTER_2020_FORM",
            "RATTATA_ALOLA_FORM", "CORSOLA_GALARIAN_FORM", "VOLTORB_HISUIAN_FORM",
            "TORNADUS_THERIAN_FORM", "UNOWN_S_FORM", "TAUROS_PALDEA_BLAZE_FORM",
            "PIKACHU_SHADOW_FORM",
        )
    ]}
    kept = {entry["id"] for entry in build_pokemon_index(blob, {})}
    for dropped in ("CHARMANDER_FALL_2019_FORM", "PIKACHU_GOTOUR_2024_A_02_FORM",
                    "CORSOLA_SPRING_2026_FORM", "BEARTIC_WINTER_2020_FORM",
                    "PIKACHU_SHADOW_FORM"):
        assert dropped not in kept, f"{dropped} should have been filtered out"
    for survivor in ("CHARMANDER", "RATTATA_ALOLA_FORM", "CORSOLA_GALARIAN_FORM",
                     "VOLTORB_HISUIAN_FORM", "TORNADUS_THERIAN_FORM", "UNOWN_S_FORM",
                     "TAUROS_PALDEA_BLAZE_FORM"):
        assert survivor in kept, f"{survivor} is a real variant and must be kept"
    print("OK: pvp costume forms dropped")


def test_pvp_rank_tables():
    """The published rank-1 spreads, which are the whole contract of the page.

    These four numbers are independently documented (GO Hub's Kingambit
    analysis, DittoBase), so a change here means our CPM table or CP formula
    drifted, not that the meta moved.
    """
    import pvp
    expected = {
        500: ((0, 14, 7), 5.5, 500),
        1500: ((0, 15, 13), 15.5, 1499),
        2500: ((0, 15, 10), 26.0, 2499),
        0: ((15, 15, 15), 50.0, 4086),
    }
    for cap, (ivs, level, cp_value) in expected.items():
        rows = pvp.rank_table(238, 203, 225, cap)
        assert len(rows) == 4096, f"cap {cap}: expected 4096 spreads, got {len(rows)}"
        _, iv_a, iv_d, iv_s, got_level, got_cp = rows[0]
        assert (iv_a, iv_d, iv_s) == ivs, f"cap {cap}: rank 1 is {(iv_a, iv_d, iv_s)}, want {ivs}"
        assert got_level == level, f"cap {cap}: level {got_level}, want {level}"
        assert got_cp == cp_value, f"cap {cap}: CP {got_cp}, want {cp_value}"

    # A hundo is a bad Great League spread -- the single most useful thing the
    # page tells people, so it is worth pinning.
    rank, _row, share = pvp.rank_of(pvp.rank_table(238, 203, 225, 1500), 15, 15, 15)
    assert rank == 387, f"hundo should rank 387 in Great, got {rank}"
    assert 0.97 < share < 0.971, f"hundo stat product share off: {share}"
    print("OK: pvp rank tables")


def test_pvp_cpm_anchors():
    import pvp
    anchors = {1: 0.094, 10: 0.4225, 20: 0.5974, 30: 0.7317, 40: 0.7903, 50: 0.8403}
    for level, expected in anchors.items():
        got = pvp.CPM[level]
        assert abs(got - expected) < 5e-5, f"CPM L{level} is {got}, want ~{expected}"
    assert len(pvp.CPM) == 101, f"expected 101 half levels to 51, got {len(pvp.CPM)}"
    print("OK: pvp cpm anchors")


def test_pvp_preevo_cp():
    """The reason the page exists: a pre-evolution powered to its own cap busts
    the cap after evolving, so the binding level is the final form's."""
    import pvp
    iv = (0, 15, 13)
    final = pvp.rank_of(pvp.rank_table(238, 203, 225, 1500), *iv)[1]
    assert final[4] == 15.5
    # At the level Kingambit needs, Pawniard still shows a small CP ...
    early = pvp.combat_power(154, 114, 128, *iv, pvp.CPM[final[4]])
    assert early == 574, f"Pawniard at L15.5 should be CP 574, got {early}"
    # ... while Pawniard's own Great League ceiling would be far too high.
    own = pvp.rank_of(pvp.rank_table(154, 114, 128, 1500), *iv)[1]
    evolved = pvp.combat_power(238, 203, 225, *iv, pvp.CPM[own[4]])
    assert evolved > 1500, f"evolving at Pawniard's own cap should bust 1500, got {evolved}"
    print("OK: pvp pre-evolution CP")


def test_pvp_search_and_family(tmp_dir=None):
    import os
    import tempfile

    import pvp
    with tempfile.TemporaryDirectory() as tmp:
        index = pvp.load_pokemon(_pvp_fixture(tmp))
        assert len(index) == 10, f"expected 10 species, got {len(index)}"

        # Substring, and a prefix hit must outrank a mid-word one.
        names = [hit["name"] for hit in pvp.search_pokemon(index, "sharp")]
        assert names == ["Bisharp"], names
        assert pvp.search_pokemon(index, "") == []

        # A Mega is a temporary battle form, not an evolution step. Sorting
        # children alphabetically once put "Mega Swampert" ahead of
        # "Swampert", so looking up Mudkip never showed the stage people
        # actually battle with.
        assert not pvp._is_battle_form({"id": "SWAMPERT"})
        assert pvp._is_battle_form({"id": "SWAMPERT_MEGA"})
        assert pvp._is_battle_form({"id": "VENUSAUR_GIGANTAMAX"})

        # A Mega is not an evolution step, so it must not extend the chain.
        # This matters beyond cosmetics: Little Cup takes Pokemon that can
        # still evolve, and a chain of [Aerodactyl, Mega Aerodactyl] would
        # have made a fully grown Aerodactyl look eligible.
        aero = [m["name"] for m in pvp.family_chain(index, index["aerodactyl"])]
        assert aero == ["Aerodactyl"], aero
        others = [m["name"] for m in pvp.family_members(index, index["aerodactyl"])
                  if m not in pvp.family_chain(index, index["aerodactyl"])]
        assert others == ["Mega Aerodactyl"], others

        # A regional form evolves into the same regional form, but the data
        # says otherwise: Alolan Raticate's parent is plain RATTATA. Without
        # matching the variant, Alolan Rattata was a chain of one, so its
        # page found no evolution and could only report that nothing ranked.
        alolan = [m["name"] for m in pvp.family_chain(index, index["rattata-alola-form"])]
        assert alolan == ["Rattata (Alolan)", "Raticate (Alolan)"], alolan
        # Reached from the other end as well.
        assert [m["name"] for m in
                pvp.family_chain(index, index["raticate-alola-form"])] == alolan
        # And the ordinary line must not pick up the regional forms.
        plain = [m["name"] for m in pvp.family_chain(index, index["rattata"])]
        assert plain == ["Rattata", "Raticate"], plain

        chain = [m["name"] for m in pvp.family_chain(index, index["bisharp"])]
        assert chain == ["Pawniard", "Bisharp", "Kingambit"], chain
        # Walking from either end gives the same line.
        assert [m["name"] for m in pvp.family_chain(index, index["kingambit"])] == chain
        # A species whose parent is missing from the dump must not loop or crash.
        assert [m["name"] for m in pvp.family_chain(index, index["azumarill"])] == ["Azumarill"]

        os.environ["PVP_DATA_PATH"] = "/nonexistent/pvp.json"
        assert pvp.load_pokemon() == {}, "missing file must yield an empty index"
        os.environ.pop("PVP_DATA_PATH")
    print("OK: pvp search and family")


def test_pvp_styles_are_reachable():
    """Every class the stylesheet targets must appear in a class attribute.

    The summary box was written as <div id="pvp-summary"> while the rule was
    .pvp-summary, so the margin separating it from the league tables did
    nothing and the sections sat flush. Dead CSS is silent, so this walks the
    other way.

    It deliberately looks only inside class="..." attributes. A first version
    searched the whole page and passed anyway, because the script mentions
    "pvp-summary" as an element id -- which is exactly the mistake being
    hunted. Matching on the id would have made the test agree with the bug.
    """
    import os
    import re
    import tempfile

    import pvp
    with tempfile.TemporaryDirectory() as tmp:
        index = pvp.load_pokemon(_pvp_fixture(tmp))
        body, script = pvp.render_pvp_page(index, "kingambit", (0, 15, 13))
        # Two separate haystacks, and the distinction is the whole point.
        # Class attributes may come from either the body or the script. The
        # looser "any quoted literal" fallback looks at the script ONLY, with
        # id lookups cut out -- because <div id="pvp-summary"> and
        # getElementById("pvp-summary") are both quoted literals that would
        # otherwise vouch for a class no element actually carries, which is
        # exactly the bug this test exists for.
        literals = re.sub(
            r"""getElementById\(\s*["'][^"']*["']\s*\)""", "", script)

        used = set()
        stems = set()
        for value in re.findall(r"""class=["']([^"']*)""", body + script):
            for token in value.split():
                used.add(token)
                # "lg-" from `class="pvp-pill lg-' + key` -- the full name is
                # built at runtime and never appears literally.
                if token.endswith("-"):
                    stems.add(token)

        selectors = sorted(set(re.findall(r"\.([a-z][a-z0-9-]+)\s*[,{:.]", pvp.PVP_STYLES)))
        assert len(selectors) > 15, f"stylesheet parse looks wrong: {selectors}"
        def reachable(name):
            if name in used:
                return True
            if any(name.startswith(stem) for stem in stems):
                return True
            # Classes handed around as values -- rankClass() returns one,
            # classList.toggle takes one -- appear as bare quoted literals.
            # Allows " pvp-tile-final" -- a class appended to an existing
            # list carries a leading space inside the literal.
            return bool(re.search(
                r"""["']\s*""" + re.escape(name) + r"""\s*["']""", literals))

        dead = [name for name in selectors if not reachable(name)]
        assert not dead, f"CSS classes no element ever carries: {dead}"
        os.environ.pop("PVP_DATA_PATH", None)
    print(f"OK: pvp styles reachable ({len(selectors)} classes)")


def test_pvp_script_parses():
    """Actually parse the page script, if a JS engine is around.

    This is here because a shipped page once had a syntax error in it and
    nothing caught it: the Python tests all passed, the HTML looked right,
    the route returned 200, and the browser silently ran nothing -- search
    box and IV dots both dead. `node --check` is the only check that would
    have seen it. Skipped where node is absent (the Docker build image), so
    it is a local and CI safety net rather than a build gate.
    """
    import shutil
    import subprocess
    import tempfile

    import pvp
    node = shutil.which("node")
    if not node:
        print("SKIP: pvp script parse (no node)")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(pvp.PVP_SCRIPT)
        path = handle.name
    try:
        result = subprocess.run([node, "--check", path], capture_output=True,
                                text=True, check=False)
        assert result.returncode == 0, f"page script does not parse:\n{result.stderr}"
    finally:
        os.unlink(path)
    print("OK: pvp script parses")


def test_pvp_script_guards_missing_dom():
    """/pvp without a species has no IV rows -- the script must cope.

    It did not: the dot listeners were attached unconditionally, threw a
    TypeError on the search-only page and took the search box down with them.
    Checked structurally because the suite has no DOM; every lookup of a
    .pvp-dots row or the results box has to be followed by a null guard.
    """
    import re

    import pvp
    script = pvp.PVP_SCRIPT
    for pattern, guard in (
        (r"querySelector\('\[data-slot=", r"if \(!row\) return;"),
        (r'getElementById\("pvp-results"\)', r"if \(target\)"),
    ):
        for match in re.finditer(pattern, script):
            tail = script[match.start():match.start() + 260]
            assert re.search(guard, tail), \
                f"unguarded DOM lookup near: {script[match.start():match.start() + 70]!r}"
    print("OK: pvp script guards missing DOM")


def test_pvp_language():
    """German is the default, English is reachable, and both names are searched."""
    import json
    import os
    import re
    import tempfile

    import pvp
    from raid import application
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PVP_DATA_PATH"] = _pvp_fixture(tmp)
        try:
            index = pvp.load_pokemon()
            # Searching matches either language, whatever is displayed.
            assert [h["slug"] for h in pvp.search_pokemon(index, "gladimp")] == ["kingambit"]
            assert [h["slug"] for h in pvp.search_pokemon(index, "kingamb")] == ["kingambit"]
            # Display follows the chosen language, with an English fallback
            # for the species the game has no German string for yet.
            assert pvp.named(index["kingambit"], "de") == "Gladimperio"
            assert pvp.named(index["kingambit"], "en") == "Kingambit"
            assert pvp.named(index["bisharp"], "de") == "Bisharp", "fallback to English"
            assert pvp.lang_from_cookies("foo=1; pvp_lang=en; bar=2") == "en"
            # Browser preference when no cookie, q-values honoured.
            assert pvp.lang_from_accept("en-GB,en;q=0.9") == "en"
            assert pvp.lang_from_accept("de-DE,de;q=0.9,en;q=0.8") == "de"
            assert pvp.lang_from_accept("en;q=0.4, de;q=0.9") == "de", "q-value ignored"
            assert pvp.lang_from_accept("fr-FR,fr;q=0.9") == "de", "unsupported -> default"
            assert pvp.lang_from_accept("de;q=bogus") == "de", "unparsable q must not throw"
            assert pvp.lang_from_accept(None) == "de"
            # An explicit cookie beats the browser, in both directions.
            assert pvp.choose_lang("pvp_lang=de", "en-US,en;q=0.9") == "de"
            assert pvp.choose_lang("pvp_lang=en", "de-DE,de;q=0.9") == "en"
            assert pvp.choose_lang("", "en-US,en;q=0.9") == "en"
            assert pvp.lang_from_cookies("pvp_lang=klingon") == "de", "unknown falls back"
            assert pvp.lang_from_cookies(None) == "de"

            captured = {}

            def start_response(status, headers):
                captured["status"] = status
                captured["headers"] = headers

            def get(path, query="", cookie=""):
                env = {"QUERY_STRING": query, "PATH_INFO": path, "SCRIPT_NAME": ""}
                if cookie:
                    env["HTTP_COOKIE"] = cookie
                return b"".join(application(env, start_response)).decode()

            html = get("/pvp/kingambit")
            assert "Gladimperio" in html, "default page should be German"
            html = get("/pvp/kingambit", cookie="pvp_lang=en")
            assert '"name": "Kingambit"' in html, "cookie should switch the language"

            # No cookie: follow the browser.
            env = {"QUERY_STRING": "", "PATH_INFO": "/pvp/kingambit", "SCRIPT_NAME": "",
                   "HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9"}
            html = b"".join(application(env, start_response)).decode()
            assert '"name": "Kingambit"' in html, "browser preference ignored"
            # Cookie must win over the browser.
            env["HTTP_COOKIE"] = "pvp_lang=de"
            html = b"".join(application(env, start_response)).decode()
            assert "Gladimperio" in html, "cookie must override the browser"

            # One language at a time. Someone playing the game in English
            # does not want German names alongside, and vice versa, so the
            # other language must not leak into the page as a subtitle or a
            # second line in the search hits. Slugs in URLs are lower case,
            # so these checks are safely case-sensitive.
            # Checked against the rendered body and the family payload rather
            # than the whole page: the script carries prose comments that
            # legitimately name Pokemon, and matching those would make this
            # fail for the wrong reason.
            for lang, wanted, unwanted in (("en", "Kingambit", "Gladimperio"),
                                           ("de", "Gladimperio", "Kingambit")):
                body, script = pvp.render_pvp_page(index, "kingambit", (0, 15, 13), lang)
                payload = re.search(r"window\.PVP_DATA = (\{.*?\});", script, re.DOTALL)
                names = [m["name"] for m in json.loads(payload.group(1))["family"]]
                assert wanted in body, f"{lang}: own language missing from the page"
                assert unwanted not in body, f"{lang}: the other language leaked in"
                assert unwanted not in names, f"{lang}: the other language leaked into {names}"
            # ... but matching stays bilingual, which is invisible and free.
            assert [h["slug"] for h in pvp.search_pokemon(index, "gladimp")] == ["kingambit"]

            get("/pvp/kingambit/0-15-13", query="lang=en")
            assert captured["status"] == "302 Found", captured["status"]
            headers = dict(captured["headers"])
            assert headers["Location"] == "/pvp/kingambit/0-15-13", headers["Location"]
            assert "pvp_lang=en" in headers["Set-Cookie"], headers["Set-Cookie"]
        finally:
            os.environ.pop("PVP_DATA_PATH", None)
    print("OK: pvp language switch")


def test_pvp_no_downgrade():
    """A page shows its own stage and upwards, never the stages below it.

    There is no way to un-evolve, so Swampert's page listing Mudkip's rank is
    noise. The pre-evolutions still travel in the payload, because the page
    needs them for the one number they are good for: the CP ceiling you have
    to stay under before evolving.
    """
    import json
    import re
    import tempfile

    import pvp
    with tempfile.TemporaryDirectory() as tmp:
        index = pvp.load_pokemon(_pvp_fixture(tmp))
        for slug, expected_index in (("pawniard", 0), ("bisharp", 1), ("kingambit", 2)):
            _body, script = pvp.render_pvp_page(index, slug, (0, 15, 13))
            payload = json.loads(
                re.search(r"window\.PVP_DATA = (\{.*?\});", script, re.DOTALL).group(1))
            names = [m["name"] for m in payload["family"]]
            assert names == ["Gladiantri", "Bisharp", "Gladimperio"], names
            assert payload["targetIndex"] == expected_index, \
                f"{slug}: targetIndex {payload['targetIndex']}, want {expected_index}"
        # The script slices on that index, so the contract is: everything from
        # targetIndex on is usable, everything before it is only a ceiling.
        # The summary slices on that index; the detail tables walk the whole
        # line. The ceiling note is anchored on the final stage instead, so
        # it works on a base-form page too -- that is where it is needed
        # most, because the level shown there belongs to the evolution.
        assert "FAMILY.slice(D.targetIndex" in script, "summary is not sliced"
        assert "FAMILY.forEach(function (mon) {\n        if (!eligible(mon, lg))" in script, \
            "detail tables no longer walk the whole family"
        assert "if (isFinal && fits) anchorLevel" in script, \
            "ceiling note is not anchored on the final stage"
    print("OK: pvp no downgrade")


def test_pvp_routes():
    import json
    import os
    import tempfile

    from raid import application
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PVP_DATA_PATH"] = _pvp_fixture(tmp)
        try:
            captured = {}

            def start_response(status, headers):
                captured["status"] = status
                captured["headers"] = dict(headers)

            def get(path):
                body = b"".join(application(
                    {"QUERY_STRING": "", "PATH_INFO": path, "SCRIPT_NAME": ""},
                    start_response))
                return captured["status"], body.decode()

            status, html = get("/pvp/kingambit/0-15-13")
            assert status == "200 OK", status
            # German is the default, so the family shows German names where
            # the fixture has them and falls back to English where it does not.
            assert "Gladimperio" in html, "selected species missing from page"
            assert "Gladiantri" in html, "pre-evolution missing from page"
            assert "Bisharp" in html, "middle stage has no German name, must fall back"
            assert '"iv": [0, 15, 13]' in html, "IVs not handed to the page"
            assert "Little Cup" in html and "Master League" in html, "leagues missing"

            # A nonsense IV path must land on the page, not 404 a bookmark.
            status, html = get("/pvp/kingambit/99-99-99")
            assert status == "200 OK" and '"iv": [0, 0, 0]' in html

            status, html = get("/pvp")
            assert status == "200 OK" and "pvp-q" in html, "search box missing"

            status, body = get("/api/pvp/index")
            assert status == "200 OK", status
            payload = json.loads(body)
            assert len(payload["pokemon"]) == 10, payload
            assert payload["pokemon"][0][0] == "aerodactyl", "index should be name-sorted"
            assert captured["headers"]["Cache-Control"].startswith("public"), \
                "species index must be cacheable"
        finally:
            os.environ.pop("PVP_DATA_PATH", None)
    print("OK: pvp routes")


if __name__ == "__main__":
    tests = [test_imports, test_wsgi_app, test_type_effectiveness,
             test_format_difficulty, test_humanize_tier, test_display_name,
             test_is_current_tier, test_icon_map_picks_the_richest_chunk,
             test_max_counter_table, test_saturated_estimators_are_dropped,
             test_icon_mirror_names_and_serving, test_max_battles_are_separated,
             test_build_raid_entries, test_format_local,
             test_api_effectiveness, test_api_raids, test_watchdog,
             test_pvp_costume_forms_are_dropped,
             test_pvp_rank_tables, test_pvp_cpm_anchors, test_pvp_preevo_cp,
             test_pvp_search_and_family, test_pvp_styles_are_reachable,
             test_pvp_script_parses,
             test_pvp_script_guards_missing_dom, test_pvp_language,
             test_pvp_no_downgrade,
             test_pvp_routes]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
    sys.exit(failed)
