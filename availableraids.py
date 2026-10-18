#!/usr/bin/env python3

"""Fetch current Pokebattler raid data and cache it locally as JSON.

Data comes from the two JSON endpoints Pokebattler's own frontend uses:

* ``/raids``   — which bosses are in rotation per tier, plus ``breakingNews``,
  which carries the schedule window (start/end) for each boss.
* ``/pokemon`` — the pokedex, which carries the boss types.

This replaced HTML scraping in October 2026, when pokebattler.com became a
client-side SPA: the server now ships a 7 KB shell, so the ``window.REHYDRATE``
blob the old scraper parsed is gone for good, as are the per-boss detail pages
it fetched icons from. The JSON endpoints are the SPA's own data source and
need no rendering, which makes them both simpler and far less brittle.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

POKEBATTLER_SITE = "https://www.pokebattler.com"
FIGHT_API_BASE = "https://fight.pokebattler.com"
RAIDS_API_URL = f"{FIGHT_API_BASE}/raids"
POKEDEX_API_URL = f"{FIGHT_API_BASE}/pokemon"
ICON_BASE_URL = "https://static.pokebattler.com/assets/pokemon/64"
DEFAULT_OUTPUT = "available_raids.json"
USER_AGENT = "Mozilla/5.0 (compatible; RaidFetcher/1.0; +https://www.pokebattler.com/)"

# Pokebattler stores raid windows as wall-clock times in California and the
# frontend reinterprets them in the viewer's own timezone ("6 AM local"). We
# render them in the source timezone and hand raid.py the matching instant;
# raid.py reads start_local back with the same RAID_SOURCE_TZ default.
SOURCE_TZ_NAME = os.environ.get("RAID_SOURCE_TZ", "America/Los_Angeles")

# How far ahead an announced raid may start and still be written out.
UPCOMING_WINDOW_SECONDS = 3 * 24 * 60 * 60

log = logging.getLogger(__name__)


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_json(url: str, session: requests.Session, timeout: int = 60) -> dict:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def source_tz() -> ZoneInfo:
    try:
        return ZoneInfo(SOURCE_TZ_NAME)
    except Exception:
        # A bad env value must not kill the run.
        log.warning("Unknown RAID_SOURCE_TZ %r, falling back to UTC", SOURCE_TZ_NAME)
        return ZoneInfo("UTC")


def is_current_tier(tier: str) -> bool:
    """True for tiers that describe the live rotation.

    ``_FUTURE`` and ``_LEGACY`` are catalogues of everything that ever ran or
    might run (several hundred entries), and ``RAID_LEVEL_UNSET`` holds the
    whole pokedex. ``_MAX`` is excluded too: Max Battles are a separate game
    mode, and is_tier_five_or_higher() in raid.py would render them as raid
    cards.
    """
    if not tier or tier == "RAID_LEVEL_UNSET":
        return False
    if tier.endswith(("_FUTURE", "_LEGACY")):
        return False
    return "_MAX" not in tier


# Name rewrites ported from Pokebattler's own bundle so our labels match the
# site's ("Shadow Landorus", "Mega Dragonite", "Arcanine (Hisuian)").
NAME_REWRITES = (
    (r"^MEWTWO_A_FORM$", "Armored Mewtwo"),
    (r"_SHADOW_FORM$", " (Shadow)"),
    (r"_GIGANTAMAX$", " (Gigantamax)"),
    (r"_DYNAMAX$", " (Dynamax)"),
    (r"^(.*)_MEGA_Y$", r"Mega \1 Y"),
    (r"^(.*)_MEGA_X$", r"Mega \1 X"),
    (r"^(.*)_MEGA$", r"Mega \1"),
    (r"_PRIMAL$", " (Primal)"),
    (r"_ALOLAN?_FORM$", " (Alolan)"),
    (r"_GALARIAN?_FORM$", " (Galarian)"),
    (r"_HISUIAN_FORM$", " (Hisuian)"),
)


def display_name(pokemon_id: str) -> str:
    name = pokemon_id or ""
    for pattern, replacement in NAME_REWRITES:
        name = re.sub(pattern, replacement, name)
    name = name.replace("_", " ").lower()
    name = re.sub(r"\b\w", lambda match: match.group(0).upper(), name)
    # The site moves the shadow marker to the front rather than keeping it in
    # parentheses, which is also how the old HTML scraper read it.
    return re.sub(r"^(.*) \(Shadow\)$", r"Shadow \1", name)


def humanize_tier(tier: str) -> str:
    tier = tier or ""
    tier_upper = tier.upper()
    if "MEGA" in tier_upper:
        return "Mega Raid"
    if "ULTRA_BEAST" in tier_upper:
        return "Ultra Beast Raid"
    if "ELITE" in tier_upper:
        return "Elite Raid"
    if "SHADOW" in tier_upper:
        level_match = re.search(r"RAID_LEVEL_(\d)", tier_upper)
        if level_match:
            return f"Shadow Tier {level_match.group(1)} Raid"
        return "Shadow Raid"
    if "RAID_LEVEL" in tier_upper:
        level_match = re.search(r"RAID_LEVEL_(\d)", tier_upper)
        if level_match:
            return f"Tier {level_match.group(1)} Raid"
    return tier.replace("_", " ").title() if tier else "Unknown"


def format_local(ms: int | None, tz: ZoneInfo) -> str | None:
    """Render an epoch-ms timestamp the way the site does: 'Oct 14, 2026 6:00 AM'."""
    if not ms:
        return None
    moment = datetime.fromtimestamp(ms / 1000, tz)
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return f"{moment:%b} {moment.day}, {moment.year} {hour}:{moment:%M} {meridiem}"


def format_utc(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def build_schedule(blob: dict) -> dict[tuple[str, str], dict]:
    """Map (pokemonId, tier) to its schedule entry from ``breakingNews``."""
    schedule: dict[tuple[str, str], dict] = {}
    for entry in blob.get("breakingNews") or []:
        pokemon = entry.get("pokemon")
        tier = entry.get("tier")
        if pokemon and tier:
            schedule[(pokemon, tier)] = entry
    return schedule


def build_raid_entries(blob: dict, icon_map: dict[str, str]) -> list[dict]:
    schedule = build_schedule(blob)
    tz = source_tz()
    now_ms = datetime.now(UTC).timestamp() * 1000
    cutoff_ms = now_ms + UPCOMING_WINDOW_SECONDS * 1000
    raids: list[dict] = []
    seen: set[str] = set()

    for tier_info in blob.get("tiers") or []:
        tier_raw = tier_info.get("tier") or ""
        if not is_current_tier(tier_raw):
            continue
        for boss in tier_info.get("raids") or []:
            slug = boss.get("pokemonId") or boss.get("pokemon")
            if not slug or slug in seen:
                continue

            window = schedule.get((slug, tier_raw), {})
            start_ms = window.get("startDate") or boss.get("startDate")
            end_ms = window.get("endDate")
            if not start_ms:
                continue
            if start_ms > cutoff_ms:
                continue
            if end_ms and end_ms < now_ms:
                continue

            seen.add(slug)
            raids.append(
                {
                    "pokemon": display_name(slug),
                    "image": icon_url(slug, icon_map),
                    "start_local": format_local(start_ms, tz),
                    "end_local": format_local(end_ms, tz),
                    "start_utc": format_utc(start_ms),
                    "end_utc": format_utc(end_ms),
                    "difficulty": None,
                    "tier": humanize_tier(tier_raw),
                    "tier_raw": tier_raw,
                    "pokebattler_url": f"{POKEBATTLER_SITE}/raids/{slug}",
                    "_slug": slug,
                }
            )

    raids.sort(key=lambda item: (item.get("start_utc") or "", item.get("pokemon") or ""))
    return raids


# Values in the icon table are game assets ("pokemon_icon_483_00.png" or
# "pm/pm149.fMEGA.icon.png"); the same chunk also holds an alternative art set
# whose values are bare "DIALGA.png" names, which this pattern skips.
ICON_ENTRY_RE = re.compile(
    r"([A-Z][A-Z0-9_]*):`((?:pokemon_icon_[0-9a-z_]+|pm/pm[0-9A-Za-z._]+)\.png)`"
)


def fetch_icon_map(session: requests.Session) -> dict[str, str]:
    """Best effort: Pokebattler's own pokemonId -> icon filename table.

    The table lives in a hash-named JS chunk, so it is discovered through the
    page and the entry bundle rather than hardcoded. Icons are decoration, so
    every failure here is a warning and an empty map, never a failed run.
    """
    try:
        html = session.get(f"{POKEBATTLER_SITE}/raids", timeout=20).text
        entry_match = re.search(r'src="(/assets/index-[^"]+\.js)"', html)
        if not entry_match:
            raise RuntimeError("entry bundle not referenced in page")
        bundle = session.get(f"{POKEBATTLER_SITE}{entry_match.group(1)}", timeout=30).text
        chunk_match = re.search(r"assets/(pokebattler-[A-Za-z0-9_-]+\.js)", bundle)
        if not chunk_match:
            raise RuntimeError("icon chunk not referenced in bundle")
        chunk = session.get(f"{POKEBATTLER_SITE}/assets/{chunk_match.group(1)}", timeout=30).text
        icon_map = dict(ICON_ENTRY_RE.findall(chunk))
        if not icon_map:
            raise RuntimeError("icon table not found in chunk")
        log.info("Icon table: %d entries", len(icon_map))
        return icon_map
    except (requests.RequestException, RuntimeError) as exc:
        log.warning("No boss icons this run: %s", exc)
        return {}


def icon_url(slug: str, icon_map: dict[str, str]) -> str | None:
    if not icon_map:
        return None
    # Shadow bosses reuse the base icon, the same fallback the site applies.
    filename = icon_map.get(slug) or icon_map.get(re.sub(r"_SHADOW_FORM$", "", slug))
    return f"{ICON_BASE_URL}/{filename}" if filename else None


def fetch_type_map(session: requests.Session) -> dict[str, list[str]]:
    """Boss types straight from the pokedex endpoint.

    This replaced per-boss PokeAPI lookups, which needed a hand-maintained
    alias table and still 404'd on forms PokeAPI names differently (the
    ZAMAZENTA_HERO_FORM warnings in the old logs).
    """
    try:
        data = fetch_json(POKEDEX_API_URL, session)
    except (requests.RequestException, ValueError) as exc:
        log.warning("No boss types this run: %s", exc)
        return {}
    type_map: dict[str, list[str]] = {}
    for mon in data.get("pokemon") or []:
        pokemon_id = mon.get("pokemonId")
        if not pokemon_id:
            continue
        type_map[pokemon_id] = [
            value.removeprefix("POKEMON_TYPE_").lower()
            for value in (mon.get("type"), mon.get("type2"))
            if value
        ]
    return type_map


def populate_types(raids: list[dict], type_map: dict[str, list[str]]) -> None:
    for raid in raids:
        slug = raid.get("_slug") or ""
        types = type_map.get(slug) or type_map.get(re.sub(r"_SHADOW_FORM$", "", slug))
        if types:
            raid["types"] = types
        else:
            log.warning("No types for %s", slug)


def fetch_estimator(slug: str, tier_raw: str, session: requests.Session) -> float | None:
    """Fetch the best-case Pokebattler Estimator for a raid boss."""
    url = (
        f"{FIGHT_API_BASE}/raids/defenders/{slug}/levels/{tier_raw}"
        "/attackers/levels/50/strategies/CINEMATIC_ATTACK_WHEN_POSSIBLE"
        "/DEFENSE_RANDOM_MC?sort=ESTIMATOR&weatherCondition=NO_WEATHER"
        "&dodgeStrategy=DODGE_REACTION_TIME&aggregation=AVERAGE"
        "&includeLegendary=true&includeShadow=true&includeMegas=true"
        "&attackerTypes=POKEMON_TYPE_ALL"
    )
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["attackers"][0]["randomMove"]["total"]["estimator"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        log.warning("Failed to fetch estimator for %s: %s", slug, exc)
        return None


def populate_estimators(raids: list[dict], session: requests.Session) -> None:
    for raid in raids:
        slug = raid.get("_slug")
        tier_raw = raid.get("tier_raw")
        if not slug or not tier_raw:
            continue
        estimator = fetch_estimator(slug, tier_raw, session)
        if estimator is not None:
            raid["difficulty"] = str(math.ceil(estimator))
            raid["difficulty_raw"] = estimator


def write_output(path: Path, payload: list[dict]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=RAIDS_API_URL, help="Raid API endpoint to read")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write the JSON payload")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with create_session() as session:
        blob = fetch_json(args.url, session)
        raids = build_raid_entries(blob, fetch_icon_map(session))
        if not raids:
            # Writing an empty file would quietly blank the site; leaving the
            # previous one in place lets the watchdog notice the staleness.
            print("No current raids found, keeping the previous data")
            return 1
        populate_types(raids, fetch_type_map(session))
        populate_estimators(raids, session)
    for raid in raids:
        raid.pop("_slug", None)
    output_path = Path(args.output)
    write_output(output_path, raids)
    print(f"Wrote {len(raids)} raids to {output_path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
