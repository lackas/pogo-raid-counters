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
    # Max Battles are a different game mode and must not become raid cards
    assert not is_current_tier("RAID_LEVEL_5_MAX")
    print("OK: is_current_tier")


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
             test_is_current_tier, test_build_raid_entries, test_format_local,
             test_api_effectiveness, test_api_raids, test_watchdog]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
    sys.exit(failed)
