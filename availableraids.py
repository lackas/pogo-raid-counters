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


def is_max_tier(tier: str) -> bool:
    """True for Max Battle tiers (``RAID_LEVEL_5_MAX``, ``RAID_LEVEL_6_MAX``, ...).

    Max Battles are a separate game mode fought at Power Spots, not at gyms.
    They are carried in the same ``tiers[]`` structure as raids, so everything
    downstream has to be able to tell them apart.
    """
    return "_MAX" in (tier or "")


def is_current_tier(tier: str) -> bool:
    """True for tiers that describe the live rotation.

    ``_FUTURE`` and ``_LEGACY`` are catalogues of everything that ever ran or
    might run (several hundred entries), and ``RAID_LEVEL_UNSET`` holds the
    whole pokedex. ``_MAX`` is kept -- Max Battles are a separate mode, but
    the data is good and the app renders them in their own section.
    """
    if not tier or tier == "RAID_LEVEL_UNSET":
        return False
    return not tier.endswith(("_FUTURE", "_LEGACY"))


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
    # Max first: RAID_LEVEL_6_MAX would otherwise never be reached, and a
    # Gigantamax boss labelled "Tier 6 Raid" sends people to a gym.
    if is_max_tier(tier_upper):
        if "RAID_LEVEL_6" in tier_upper:
            return "Gigantamax"
        level_match = re.search(r"RAID_LEVEL_(\d)", tier_upper)
        if level_match:
            return f"Max Battle Tier {level_match.group(1)}"
        return "Max Battle"
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
    # Keyed by (slug, mode), not by slug alone: a species can be a raid boss
    # and a Max Battle at the same time (Sableye was both in Nov 2026), and
    # dropping one of the two would hide a mode that is genuinely running.
    seen: set[tuple[str, bool]] = set()

    for tier_info in blob.get("tiers") or []:
        tier_raw = tier_info.get("tier") or ""
        if not is_current_tier(tier_raw):
            continue
        is_max = is_max_tier(tier_raw)
        for boss in tier_info.get("raids") or []:
            slug = boss.get("pokemonId") or boss.get("pokemon")
            if not slug or (slug, is_max) in seen:
                continue

            window = schedule.get((slug, tier_raw), {})
            start_ms = window.get("startDate") or boss.get("startDate")
            end_ms = window.get("endDate")
            if start_ms:
                if start_ms > cutoff_ms:
                    continue
                if end_ms and end_ms < now_ms:
                    continue
            elif not is_max:
                # A raid without a window is an announcement we cannot place
                # on a calendar, so it stays out.
                continue
            # A Max Battle without a window is the standing Power-Spot
            # rotation (tiers 1-4). Those have no start or end -- they are
            # simply available -- so a missing schedule must not drop them.
            # Only tiers 5 and 6 get dated windows in breakingNews.

            seen.add((slug, is_max))
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
                    "max_battle": is_max,
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


# Chunks that have held the icon table, most recently first. Pokebattler
# split it out of `pokebattler-*` into a dedicated `pokemon-icons-*` chunk
# some time before 2026-11-14; the old chunk kept ten stale Mega entries, so
# the scrape still "succeeded" and every boss silently lost its picture.
# Hence: try every candidate and keep the richest table, instead of trusting
# the first one that yields anything at all.
ICON_CHUNK_PATTERNS = (
    r"assets/(pokemon-icons-[A-Za-z0-9_-]+\.js)",
    r"assets/(pokebattler-[A-Za-z0-9_-]+\.js)",
)

# Below this, assume we found a leftover rather than the real table. The real
# one carried 2332 entries on 2026-11-14, the stale chunk 10.
MIN_ICON_ENTRIES = 100


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

        best: dict[str, str] = {}
        tried = []
        for pattern in ICON_CHUNK_PATTERNS:
            for name in dict.fromkeys(re.findall(pattern, bundle)):
                chunk = session.get(f"{POKEBATTLER_SITE}/assets/{name}", timeout=30).text
                candidate = dict(ICON_ENTRY_RE.findall(chunk))
                tried.append(f"{name}={len(candidate)}")
                if len(candidate) > len(best):
                    best = candidate
            if len(best) >= MIN_ICON_ENTRIES:
                break

        if not best:
            raise RuntimeError(f"icon table not found (tried {', '.join(tried) or 'nothing'})")
        if len(best) < MIN_ICON_ENTRIES:
            # Loud, because the symptom is invisible: bosses just lose their
            # pictures and nothing else breaks.
            log.warning(
                "Icon table suspiciously small: %d entries (tried %s) -- "
                "Pokebattler probably moved it again",
                len(best), ", ".join(tried),
            )
        log.info("Icon table: %d entries", len(best))
        return best
    except (requests.RequestException, RuntimeError) as exc:
        log.warning("No boss icons this run: %s", exc)
        return {}


def icon_url(slug: str, icon_map: dict[str, str]) -> str | None:
    if not icon_map:
        return None
    # Shadow bosses reuse the base icon, the same fallback the site applies.
    filename = icon_map.get(slug) or icon_map.get(re.sub(r"_SHADOW_FORM$", "", slug))
    return f"{ICON_BASE_URL}/{filename}" if filename else None


# Pokebattler's Max Battle numbers come from a precomputed table shipped as a
# JS asset, not from an API. The live calculator behind their /max/ pages
# (`max-ranking`, `max-battle`) sits behind a JWT and a quota gate; this table
# does not. Reached by walking a chain of hash-named chunks, same idea as the
# icon table:
#     /max/<anything>  ->  useMaxData-*.js  ->  maxbattles-*.js
#                      ->  max-bosses-compact-*.js
MAX_COUNTER_CHAIN = (
    r"(useMaxData-[A-Za-z0-9_-]+\.js)",
    r"(maxbattles-[A-Za-z0-9_-]+\.js)",
    r"(max-bosses-compact-[A-Za-z0-9_-]+\.js)",
)

# Eternamax Eternatus is a raid-exclusive form almost nobody owns, and it tops
# every single list by a wide margin (Entei: 0.74 against 2.90 for the next
# one). Counting it would turn every trainer estimate into a number that only
# a handful of players could reproduce.
UNOBTAINABLE_MAX_COUNTERS = frozenset({"ETERNATUS_ETERNAMAX_FORM"})

# How many counters to carry per boss. The table holds up to 20; the tail is
# noise for a phone screen.
MAX_COUNTERS_KEPT = 5

# Above this the estimator has stopped measuring and is just pinned to its
# ceiling. Checked on 2026-11-14: for every tier 4 and 5 boss the values
# spread cleanly (Toxtricity 1.09..4.58, Registeel 1.94..7.58, nothing above
# 90). For both tier 6 bosses three quarters of the list sits at 96..99.5 --
# and Gigantamax Machamp, which every guide names as *the* counter against
# fighting-weak Duraludon, comes dead last at 99.52. The model clearly does
# not represent a Gigantamax fight, which is run in groups of four with Max
# Guard tanks and Max Spirit healers rather than by everyone attacking.
SATURATED_ESTIMATOR = 90.0
SATURATED_SHARE = 0.5


def _is_saturated(estimators: list[float]) -> bool:
    """True when most of the list is pinned at the ceiling (see above)."""
    if not estimators:
        return True
    pinned = sum(1 for e in estimators if e > SATURATED_ESTIMATOR)
    return pinned / len(estimators) > SATURATED_SHARE


def _js_object_to_json(text: str) -> dict:
    """Decode the `var e={...}` literal of a Pokebattler chunk.

    Their bundler emits backtick strings and bare identifier keys, so it is
    valid JS but not valid JSON.
    """
    start = text.index("var e={") + len("var e=")
    end = text.index(";export{", start)
    literal = text[start:end].replace("`", '"')
    literal = re.sub(r"([{,])([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', literal)
    return json.loads(literal)


def fetch_max_counters(session: requests.Session) -> dict[str, dict]:
    """Best effort: Pokebattler's precomputed Max Battle counters.

    Returns ``{pokemonId: {"difficulty_raw": float, "counters": [...]}}``.
    Like the icons, this is decoration on top of a run that must succeed
    without it -- every failure is a warning and an empty map.
    """
    try:
        url = f"{POKEBATTLER_SITE}/max/DYNAMAX_DIALGA"
        text = session.get(url, timeout=30).text
        for pattern in MAX_COUNTER_CHAIN:
            match = re.search(pattern, text)
            if not match:
                raise RuntimeError(f"chunk matching {pattern} not referenced")
            url = f"{POKEBATTLER_SITE}/assets/{match.group(1)}"
            text = session.get(url, timeout=30).text

        raw = _js_object_to_json(text)
        table: dict[str, dict] = {}
        skipped: list[str] = []
        for boss, entry in raw.items():
            counters = []
            for c in entry.get("c") or []:
                if c.get("p") in UNOBTAINABLE_MAX_COUNTERS:
                    continue
                try:
                    estimator = float(c["e"])
                except (KeyError, TypeError, ValueError):
                    continue
                counters.append(
                    {
                        "pokemon": display_name(c["p"]),
                        "quick_move": c.get("m1"),
                        "charged_move": c.get("m2"),
                        "estimator": round(estimator, 2),
                    }
                )
            if not counters:
                continue
            counters.sort(key=lambda item: item["estimator"])
            if _is_saturated([c["estimator"] for c in counters]):
                # Both number and ranking are unusable here, so publish
                # neither. Better an empty card than a confident 74.
                log.info("Max Battle counters: skipping %s, estimator saturated", boss)
                skipped.append(boss)
                continue
            table[boss] = {
                "difficulty_raw": counters[0]["estimator"],
                "counters": counters[:MAX_COUNTERS_KEPT],
            }
        if not table:
            raise RuntimeError("counter table parsed but empty")
        log.info(
            "Max Battle counters: %d bosses (%d skipped as saturated)",
            len(table), len(skipped),
        )
        return table
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        log.warning("No Max Battle counters this run: %s", exc)
        return {}


def populate_max_counters(raids: list[dict], table: dict[str, dict]) -> None:
    """Attach trainer estimate and counters to the Max Battle entries.

    The table lags the rotation -- on 2026-11-14 it had 50 of the 61 live
    bosses and was missing both current tier-5 ones -- so a miss is normal
    and must leave the entry untouched rather than blank it.
    """
    if not table:
        return
    hits = 0
    for raid in raids:
        if not raid.get("max_battle"):
            continue
        entry = table.get(raid.get("_slug") or "")
        if not entry:
            continue
        raid["difficulty"] = str(math.ceil(entry["difficulty_raw"]))
        raid["difficulty_raw"] = entry["difficulty_raw"]
        raid["counters"] = entry["counters"]
        hits += 1
    total = sum(1 for r in raids if r.get("max_battle"))
    log.info("Max Battle counters matched: %d of %d", hits, total)


# Where mirrored icons live, and the path the app serves them under. They are
# kept next to the data file so one volume holds everything stateful.
DEFAULT_ICON_DIR = "/data/icons"
DEFAULT_PVP_OUTPUT = "/data/pvp_pokemon.json"
PVP_ICON_BUDGET = 400
ICON_ROUTE = "/icons"

# A mirrored name must survive being put in a URL and a filename, and
# Pokebattler's newer set has a directory in it ("pm/pm884.icon.png").
ICON_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def mirrored_icon_name(remote_filename: str) -> str:
    return ICON_SAFE_RE.sub("_", remote_filename)


def mirror_icons(raids: list[dict], session: requests.Session, icon_dir: str) -> None:
    """Copy each boss icon once, then serve it from here instead of hotlinking.

    Two reasons, and traffic is not one of them -- the site sees a handful of
    visits a day. First, every page view currently fetches ~30 images from
    Pokebattler's CDN; mirroring ends that. Second and more useful: once a
    file is here it stays. When the icon table broke on 2026-11-14 every boss
    lost its picture at once; with a mirror the old files would simply have
    remained in place.

    Already-mirrored files are never re-fetched, so a normal run makes zero
    requests. Failures are per-icon and silent-ish: the entry keeps its remote
    URL, which still works.
    """
    directory = Path(icon_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Cannot mirror icons into %s: %s", icon_dir, exc)
        return

    fetched = reused = failed = 0
    for raid in raids:
        url = raid.get("image") or ""
        if not url.startswith(ICON_BASE_URL):
            continue
        remote = url[len(ICON_BASE_URL) :].lstrip("/")
        name = mirrored_icon_name(remote)
        target = directory / name
        if target.exists() and target.stat().st_size > 0:
            reused += 1
        else:
            try:
                resp = session.get(url, timeout=20)
                resp.raise_for_status()
                if not resp.content:
                    raise RuntimeError("empty body")
                # Write via a temp name so an interrupted run cannot leave a
                # half file that later looks mirrored.
                tmp = target.with_suffix(target.suffix + ".part")
                tmp.write_bytes(resp.content)
                tmp.replace(target)
                fetched += 1
            except (requests.RequestException, RuntimeError, OSError) as exc:
                log.warning("Icon not mirrored (%s): %s", remote, exc)
                failed += 1
                continue  # keep the remote URL, it still works
        raid["image"] = f"{ICON_ROUTE}/{name}"

    log.info("Icons mirrored: %d new, %d already here, %d failed", fetched, reused, failed)


def fetch_pokedex(session: requests.Session) -> dict:
    """The /pokemon blob, or {} on failure.

    Split out from fetch_type_map because two consumers need it now: boss
    types and the PvP species dump. It is ~415 KB gzipped and answers in well
    under a second, but fetching it twice per run would still be sloppy.
    """
    try:
        return fetch_json(POKEDEX_API_URL, session)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Pokedex unavailable this run: %s", exc)
        return {}


def type_map_from_pokedex(data: dict) -> dict[str, list[str]]:
    """Boss types straight from the pokedex endpoint.

    This replaced per-boss PokeAPI lookups, which needed a hand-maintained
    alias table and still 404'd on forms PokeAPI names differently (the
    ZAMAZENTA_HERO_FORM warnings in the old logs).
    """
    type_map: dict[str, list[str]] = {}
    for mon in (data or {}).get("pokemon") or []:
        pokemon_id = mon.get("pokemonId")
        if not pokemon_id:
            continue
        type_map[pokemon_id] = [
            value.removeprefix("POKEMON_TYPE_").lower()
            for value in (mon.get("type"), mon.get("type2"))
            if value
        ]
    return type_map


def fetch_type_map(session: requests.Session) -> dict[str, list[str]]:
    return type_map_from_pokedex(fetch_pokedex(session))


def populate_types(raids: list[dict], type_map: dict[str, list[str]]) -> None:
    for raid in raids:
        slug = raid.get("_slug") or ""
        types = type_map.get(slug) or type_map.get(re.sub(r"_SHADOW_FORM$", "", slug))
        if types:
            raid["types"] = types
        else:
            log.warning("No types for %s", slug)


# Schattenformen haben identische Basiswerte -- fuer den IV-Rang waeren sie
# exakte Dubletten und wuerden die Suche nur zumuellen. Der Kampfbonus der
# Schattenform wirkt im Kampf, nicht auf die Werte.
PVP_SKIP_SUFFIXES = ("_SHADOW_FORM",)


def build_pokemon_index(data: dict, icon_map: dict[str, str]) -> list[dict]:
    """Every species with base stats, for the PvP IV calculator.

    Deliberately a flat list rather than the raid shape: this one is keyed by
    species, carries no schedule and never goes stale in the way raid data
    does. `parent` and `family` are what lets the page walk an evolution line,
    which is the whole point -- powering a Pawniard to its own cap and then
    evolving it blows past 1500 as a Kingambit.
    """
    entries: list[dict] = []
    for mon in (data or {}).get("pokemon") or []:
        pokemon_id = mon.get("pokemonId")
        stats = mon.get("stats") or {}
        attack = stats.get("baseAttack")
        defense = stats.get("baseDefense")
        stamina = stats.get("baseStamina")
        if not pokemon_id or not (attack and defense and stamina):
            continue
        if any(pokemon_id.endswith(suffix) for suffix in PVP_SKIP_SUFFIXES):
            continue
        entries.append({
            "id": pokemon_id,
            "slug": re.sub(r"[^a-z0-9]+", "-", pokemon_id.lower()).strip("-"),
            "name": display_name(pokemon_id),
            "atk": attack,
            "def": defense,
            "sta": stamina,
            "types": [
                value.removeprefix("POKEMON_TYPE_").lower()
                for value in (mon.get("type"), mon.get("type2"))
                if value
            ],
            "parent": mon.get("parentPokemonId"),
            "family": mon.get("familyId"),
            "image": icon_url(pokemon_id, icon_map),
        })
    entries.sort(key=lambda entry: entry["name"])
    return entries


def write_pokemon_index(path: Path, entries: list[dict]) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pokemon": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


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
        if raid.get("max_battle"):
            # The endpoint answers for _MAX tiers, but the number is wrong and
            # wrong in a dangerous direction. Checked on 2026-11-14 for Dialga:
            # the raid entry declares hp 13000 at cpm 0.7, the simulation ran
            # stamina 9080 at level 40 with ordinary charged moves -- no Max
            # phases, no Max Move levels, no four-trainer cap. It returned
            # estimator 1.278, i.e. "2 trainers", for a boss that takes a full
            # group. Publishing that would send someone to a Power Spot alone.
            # Max Battles get their number from fetch_max_counters() instead,
            # which reads Pokebattler's own precomputed Max table.
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
    parser.add_argument(
        "--icon-dir",
        default=os.environ.get("RAID_ICON_DIR", DEFAULT_ICON_DIR),
        help="Mirror boss icons here and serve them locally ('' disables mirroring)",
    )
    parser.add_argument(
        "--pvp-output",
        default=os.environ.get("PVP_DATA_PATH", DEFAULT_PVP_OUTPUT),
        help="Path for the PvP species dump ('' skips it)",
    )
    parser.add_argument(
        "--pvp-icon-budget",
        type=int,
        default=PVP_ICON_BUDGET,
        help="Max species icons to mirror per run (they fill in over a few nights)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with create_session() as session:
        blob = fetch_json(args.url, session)
        icon_map = fetch_icon_map(session)
        raids = build_raid_entries(blob, icon_map)
        if not raids:
            # Writing an empty file would quietly blank the site; leaving the
            # previous one in place lets the watchdog notice the staleness.
            print("No current raids found, keeping the previous data")
            return 1
        pokedex = fetch_pokedex(session)
        populate_types(raids, type_map_from_pokedex(pokedex))
        populate_estimators(raids, session)
        populate_max_counters(raids, fetch_max_counters(session))
        if args.icon_dir:
            mirror_icons(raids, session, args.icon_dir)

        # The PvP dump reuses the pokedex blob and the icon table that the
        # raid side already fetched. It must never be able to fail the run:
        # the raid page is the primary product, the calculator is extra.
        species: list[dict] = []
        if args.pvp_output:
            try:
                species = build_pokemon_index(pokedex, icon_map)
                if args.icon_dir and species:
                    # ~1660 species against ~75 raid bosses, so this is
                    # budgeted: a few hundred per night, and after a week the
                    # whole set is local. Until then an unmirrored entry keeps
                    # its remote URL and still renders.
                    mirror_icons(
                        [e for e in species if e.get("image")][: args.pvp_icon_budget],
                        session, args.icon_dir,
                    )
            except Exception as exc:  # noqa: BLE001 - never fail the raid run
                log.warning("PvP species dump skipped: %s", exc)
                species = []

    for raid in raids:
        raid.pop("_slug", None)
    output_path = Path(args.output)
    write_output(output_path, raids)
    print(f"Wrote {len(raids)} raids to {output_path}")
    if species:
        pvp_path = Path(args.pvp_output)
        write_pokemon_index(pvp_path, species)
        print(f"Wrote {len(species)} species to {pvp_path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
