#!/usr/bin/env python3

import html
import json
import math
import os
import re
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs
from wsgiref.handlers import CGIHandler
from zoneinfo import ZoneInfo

import pvp

# List of all Pokémon Go types
pokemon_types = [
    "normal", "fire", "water", "electric", "grass", "ice", "fighting",
    "poison", "ground", "flying", "psychic", "bug", "rock", "ghost",
    "dragon", "dark", "steel", "fairy"
]

# Battle multipliers for readability
SUPER_EFFECTIVE = 1.6
NOT_VERY_EFFECTIVE = 0.625
DOUBLE_NOT_VERY_EFFECTIVE = NOT_VERY_EFFECTIVE ** 2  # 0.390625
NEUTRAL = 1.0
DOUBLE_EFFECTIVE_THRESHOLD = 2.0

type_color_palette = {
    "normal": {"bg": "#a8a77a", "text": "#1f1f1f"},
    "fire": {"bg": "#ee8130", "text": "#ffffff"},
    "water": {"bg": "#6390f0", "text": "#ffffff"},
    "electric": {"bg": "#f7d02c", "text": "#1f1f1f"},
    "grass": {"bg": "#7ac74c", "text": "#1f1f1f"},
    "ice": {"bg": "#96d9d6", "text": "#1f1f1f"},
    "fighting": {"bg": "#c22e28", "text": "#ffffff"},
    "poison": {"bg": "#a33ea1", "text": "#ffffff"},
    "ground": {"bg": "#e2bf65", "text": "#1f1f1f"},
    "flying": {"bg": "#a98ff3", "text": "#ffffff"},
    "psychic": {"bg": "#f95587", "text": "#ffffff"},
    "bug": {"bg": "#a6b91a", "text": "#1f1f1f"},
    "rock": {"bg": "#b6a136", "text": "#1f1f1f"},
    "ghost": {"bg": "#735797", "text": "#ffffff"},
    "dragon": {"bg": "#6f35fc", "text": "#ffffff"},
    "dark": {"bg": "#705746", "text": "#ffffff"},
    "steel": {"bg": "#b7b7ce", "text": "#1f1f1f"},
    "fairy": {"bg": "#d685ad", "text": "#1f1f1f"}
}

TYPE_BADGE_STYLES = '\n        '.join([
    f'.type-{ptype} {{ background-color: {cfg["bg"]}; color: {cfg["text"]}; }}'
    for ptype, cfg in type_color_palette.items()
])

# Type effectiveness chart
type_effectiveness = {
    "normal": {"rock": NOT_VERY_EFFECTIVE, "ghost": DOUBLE_NOT_VERY_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "fire": {"fire": NOT_VERY_EFFECTIVE, "water": NOT_VERY_EFFECTIVE, "grass": SUPER_EFFECTIVE, "ice": SUPER_EFFECTIVE, "bug": SUPER_EFFECTIVE, "rock": NOT_VERY_EFFECTIVE, "dragon": NOT_VERY_EFFECTIVE, "steel": SUPER_EFFECTIVE},
    "water": {"fire": SUPER_EFFECTIVE, "water": NOT_VERY_EFFECTIVE, "grass": NOT_VERY_EFFECTIVE, "ground": SUPER_EFFECTIVE, "rock": SUPER_EFFECTIVE, "dragon": NOT_VERY_EFFECTIVE},
    "electric": {"water": SUPER_EFFECTIVE, "electric": NOT_VERY_EFFECTIVE, "grass": NOT_VERY_EFFECTIVE, "ground": DOUBLE_NOT_VERY_EFFECTIVE, "flying": SUPER_EFFECTIVE, "dragon": NOT_VERY_EFFECTIVE},
    "grass": {"fire": NOT_VERY_EFFECTIVE, "water": SUPER_EFFECTIVE, "grass": NOT_VERY_EFFECTIVE, "poison": NOT_VERY_EFFECTIVE, "ground": SUPER_EFFECTIVE, "flying": NOT_VERY_EFFECTIVE, "bug": NOT_VERY_EFFECTIVE, "rock": SUPER_EFFECTIVE, "dragon": NOT_VERY_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "ice": {"fire": NOT_VERY_EFFECTIVE, "water": NOT_VERY_EFFECTIVE, "grass": SUPER_EFFECTIVE, "ice": NOT_VERY_EFFECTIVE, "ground": SUPER_EFFECTIVE, "flying": SUPER_EFFECTIVE, "dragon": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "fighting": {"normal": SUPER_EFFECTIVE, "ice": SUPER_EFFECTIVE, "poison": NOT_VERY_EFFECTIVE, "flying": NOT_VERY_EFFECTIVE, "psychic": NOT_VERY_EFFECTIVE, "bug": NOT_VERY_EFFECTIVE, "rock": SUPER_EFFECTIVE, "ghost": DOUBLE_NOT_VERY_EFFECTIVE, "dark": SUPER_EFFECTIVE, "steel": SUPER_EFFECTIVE, "fairy": NOT_VERY_EFFECTIVE},
    "poison": {"grass": SUPER_EFFECTIVE, "poison": NOT_VERY_EFFECTIVE, "ground": NOT_VERY_EFFECTIVE, "rock": NOT_VERY_EFFECTIVE, "ghost": NOT_VERY_EFFECTIVE, "steel": DOUBLE_NOT_VERY_EFFECTIVE, "fairy": SUPER_EFFECTIVE},
    "ground": {"fire": SUPER_EFFECTIVE, "electric": SUPER_EFFECTIVE, "grass": NOT_VERY_EFFECTIVE, "poison": SUPER_EFFECTIVE, "flying": DOUBLE_NOT_VERY_EFFECTIVE, "bug": NOT_VERY_EFFECTIVE, "rock": SUPER_EFFECTIVE, "steel": SUPER_EFFECTIVE},
    "flying": {"electric": NOT_VERY_EFFECTIVE, "grass": SUPER_EFFECTIVE, "fighting": SUPER_EFFECTIVE, "bug": SUPER_EFFECTIVE, "rock": NOT_VERY_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "psychic": {"fighting": SUPER_EFFECTIVE, "poison": SUPER_EFFECTIVE, "psychic": NOT_VERY_EFFECTIVE, "dark": DOUBLE_NOT_VERY_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "bug": {"fire": NOT_VERY_EFFECTIVE, "grass": SUPER_EFFECTIVE, "fighting": NOT_VERY_EFFECTIVE, "poison": NOT_VERY_EFFECTIVE, "flying": NOT_VERY_EFFECTIVE, "psychic": SUPER_EFFECTIVE, "ghost": NOT_VERY_EFFECTIVE, "dark": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE, "fairy": NOT_VERY_EFFECTIVE},
    "rock": {"fire": SUPER_EFFECTIVE, "ice": SUPER_EFFECTIVE, "fighting": NOT_VERY_EFFECTIVE, "ground": NOT_VERY_EFFECTIVE, "flying": SUPER_EFFECTIVE, "bug": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE},
    "ghost": {"normal": DOUBLE_NOT_VERY_EFFECTIVE, "psychic": SUPER_EFFECTIVE, "ghost": SUPER_EFFECTIVE, "dark": NOT_VERY_EFFECTIVE},
    "dragon": {"dragon": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE, "fairy": DOUBLE_NOT_VERY_EFFECTIVE},
    "dark": {"fighting": NOT_VERY_EFFECTIVE, "psychic": SUPER_EFFECTIVE, "ghost": SUPER_EFFECTIVE, "dark": NOT_VERY_EFFECTIVE, "fairy": NOT_VERY_EFFECTIVE},
    "steel": {"fire": NOT_VERY_EFFECTIVE, "water": NOT_VERY_EFFECTIVE, "electric": NOT_VERY_EFFECTIVE, "ice": SUPER_EFFECTIVE, "rock": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE, "fairy": SUPER_EFFECTIVE},
    "fairy": {"fire": NOT_VERY_EFFECTIVE, "fighting": SUPER_EFFECTIVE, "poison": NOT_VERY_EFFECTIVE, "dragon": SUPER_EFFECTIVE, "dark": SUPER_EFFECTIVE, "steel": NOT_VERY_EFFECTIVE}
}

# Function to calculate effectiveness for dual-type raid bosses
def calculate_effectiveness(raid_type1, raid_type2=None):
    effective_attackers = []
    double_attackers = []
    resisting_attackers = []
    for attacker, defender_dict in type_effectiveness.items():
        effectiveness1 = defender_dict.get(raid_type1, NEUTRAL)
        effectiveness2 = defender_dict.get(raid_type2, NEUTRAL) if raid_type2 else NEUTRAL
        combined_effectiveness = effectiveness1 * effectiveness2
        if combined_effectiveness > NEUTRAL:
            effective_attackers.append(attacker)
        elif combined_effectiveness < NEUTRAL:
            resisting_attackers.append(attacker)
        if combined_effectiveness > DOUBLE_EFFECTIVE_THRESHOLD:
            double_attackers.append(attacker)
    return (effective_attackers, double_attackers, resisting_attackers)

# Function to generate search string in the desired format
def generate_search_string(effective_attackers):
    if not effective_attackers:
        return ""
    part1 = [f"@1{attacker}" for attacker in effective_attackers]
    part2_and_3 = [f"@2{attacker},@3{attacker}" for attacker in effective_attackers]
    search_string = f"{','.join(part1)}&{','.join(part2_and_3)}"
    return search_string

# Function to generate dropdown HTML
def generate_dropdown(name, selected_value=None):
    sorted_types = sorted(pokemon_types)
    options = ''.join([f'<option value="{ptype}"{" selected" if ptype == selected_value else ""}>{ptype.capitalize()}</option>' for ptype in sorted_types])
    return f'<select id="{name}" name="{name}"><option value="">--Select--</option>{options}</select>'


def render_copy_block(label_text, content, element_id):
    escaped_content = html.escape(content)
    rows = max(1, min(6, (len(content) // 80) + 1))
    return (
        # f'<label for="{element_id}">{label_text}</label>'
        f'<div class="copy-row">'
        f'<textarea id="{element_id}" rows="{rows}" readonly>{escaped_content}</textarea>'
        f'<button type="button" class="secondary outline" data-copy-target="{element_id}">Copy</button>'
        f'</div>'
    )


def render_type_badges(label_text, types, tag='p'):
    tag = tag or 'p'
    escaped_label = html.escape(label_text) if label_text else ''
    if not types:
        if escaped_label:
            return f'<{tag}>{escaped_label}: None</{tag}>'
        return f'<{tag}>None</{tag}>'
    badges = ''.join([f'<span class="type-badge type-{ptype}">{ptype.capitalize()}</span>' for ptype in types])
    prefix = f'{escaped_label}: ' if escaped_label else ''
    return f'<{tag}>{prefix}{badges}</{tag}>'

def render_boss_card(boss):
    """One card, used for both raid bosses and Max Battle bosses."""
    image_html = (
        f'<img src="{html.escape(boss["image"])}" alt="{html.escape(boss["pokemon"])}" style="max-width:100px;display:block;">'
        if boss.get("image") else ''
    )
    link_start = (
        f'<a href="{html.escape(boss["url"])}" target="_blank" rel="noopener">'
        if boss.get("url") else '<span>'
    )
    link_end = '</a>' if boss.get("url") else '</span>'
    card_class = "upcoming" if boss.get("state") == "upcoming" else ""
    tier_badge = (
        f"<span class='raid-badge {boss.get('tier_class', '')}'>{html.escape(boss.get('tier', ''))}</span>"
        if boss.get("tier") else ""
    )
    difficulty_text = boss.get("difficulty")
    diff_class = difficulty_class(boss.get("difficulty_level"))
    difficulty_badge = (
        f"<span class='raid-badge {diff_class}'>{html.escape(difficulty_text)}</span>"
        if difficulty_text else ""
    )
    badge_row = f"<div class='raid-badge-row'>{tier_badge}{difficulty_badge}</div>"
    boss_types = boss.get("types", [])
    if boss_types:
        type_path = "/".join(boss_types)
        type_badges = "".join(
            f"<span class='type-badge type-{t}'>{t.capitalize()}</span>"
            for t in boss_types
        )
        type_html = f"<a href='/{type_path}' class='raid-badge-row' style='text-decoration:none;'>{type_badges}</a>"
    else:
        type_html = ""
    # Named counters, for Max Battles where a type badge is not enough: you
    # cannot bring "a fighting type", you bring the Pokemon you actually have
    # levelled as a Max attacker.
    counters = boss.get("counters") or []
    if counters:
        items = "".join(
            f"<li>{html.escape(c.get('pokemon', ''))}</li>" for c in counters[:3]
        )
        counter_html = f"<details class='counters'><summary>Counters</summary><ul>{items}</ul></details>"
    else:
        counter_html = ""
    return (
        f"<article class='raid-card {card_class}'>"
        f"{image_html}{link_start}<strong>{html.escape(boss['pokemon'])}</strong>{link_end}"
        f"{type_html}{badge_row}<p>{boss['status']}</p>{counter_html}</article>"
    )


def max_tier_number(tier_label):
    """Numeric tier behind a rendered Max label ('Max 3', 'Gigantamax').

    Gigantamax carries no digit but is the top tier, so it must not sort as 0
    and fall out of a 'tier 3 and up' filter.
    """
    label = (tier_label or "").strip()
    if label.lower() == "gigantamax":
        return 6
    match = re.search(r"(\d)", label)
    return int(match.group(1)) if match else 0


def render_boss_section(bosses, heading, note=None):
    """A headed grid of boss cards, or nothing at all when the list is empty."""
    if not bosses:
        return ""
    note_html = f"<p class='section-note'>{html.escape(note)}</p>" if note else ""
    cards = "".join(render_boss_card(boss) for boss in bosses)
    return (
        f"<section><h2>{html.escape(heading)}</h2>{note_html}"
        f'<div class="raid-grid">{cards}</div></section>'
    )


# Ensure only canonical type names are used when rendering output
def normalize_type(value):
    value = (value or '').strip().lower()
    return value if value in pokemon_types else ''


def parse_local_timestamp(value, local_tz):
    """Parse a localized timestamp like 'Sep 16, 2025 6:00 AM' in the given timezone."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%b %d, %Y %I:%M %p")
        return dt.replace(tzinfo=local_tz)
    except ValueError:
        return None


def _read_raid_data(path=None):
    data_path = path or os.environ.get("RAID_DATA_PATH") or "/data/available_raids.json"
    if not os.path.exists(data_path):
        return []
    try:
        with open(data_path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return []


def _source_tz():
    # Timestamps from the source site appear to use California time; default to that unless overridden.
    source_tz_name = os.environ.get("RAID_SOURCE_TZ", "America/Los_Angeles")
    try:
        return ZoneInfo(source_tz_name)
    except Exception:
        return ZoneInfo("UTC")


def is_max_battle(raid):
    """Max Battles are fought at Power Spots, not at gyms.

    The flag is written by availableraids.py; the tier string is the fallback
    for data files written before Max Battles were included.
    """
    if raid.get("max_battle"):
        return True
    return "_MAX" in (raid.get("tier_raw") or "").upper()


def _build_entry(raid, now, local_tz):
    """Shared shape for a raid card and a Max Battle card.

    Returns None for anything already over.
    """
    tier_label = raid.get("tier_raw") or raid.get("tier", "")
    start = parse_timestamp(raid.get("start_utc"))
    end = parse_timestamp(raid.get("end_utc"))
    # Prefer local timestamps if provided, converting to UTC for consistent comparison.
    start_local = parse_local_timestamp(raid.get("start_local"), local_tz)
    end_local = parse_local_timestamp(raid.get("end_local"), local_tz)
    if start_local:
        start = start_local.astimezone(UTC)
    if end_local:
        end = end_local.astimezone(UTC)
    if end and end < now:
        return None
    diff_text, diff_value = format_difficulty_label(raid.get("difficulty"))
    return {
        "pokemon": raid.get("pokemon", "Unknown"),
        "image": raid.get("image"),
        "url": raid.get("pokebattler_url"),
        "tier": humanize_tier_label(tier_label or raid.get("tier", "")),
        "tier_class": classify_tier_badge(tier_label or raid.get("tier", "")),
        "start": start,
        "end": end,
        # A Max Battle with no window is the standing Power-Spot rotation,
        # not something scheduled; saying "ends in 3h" would be a lie.
        "status": humanize_schedule(now, start, end) if (start or end) else "Always available",
        "types": raid.get("types", []),
        "difficulty": diff_text,
        "difficulty_level": diff_value,
        "max_battle": is_max_battle(raid),
        "counters": raid.get("counters") or [],
        "state": "active" if (start is None or start <= now) else "upcoming",
    }


def _sorted_entries(active, upcoming):
    active.sort(key=lambda item: item.get("end") or datetime.max.replace(tzinfo=UTC))
    upcoming.sort(key=lambda item: item.get("start") or datetime.max.replace(tzinfo=UTC))
    return active + upcoming


def load_available_raids(path=None):
    now = datetime.now(UTC)
    local_tz = _source_tz()
    active = []
    upcoming = []
    for raid in _read_raid_data(path):
        # Max Battles are excluded by flag, not by tier: RAID_LEVEL_5_MAX and
        # _6_MAX both pass is_tier_five_or_higher() and would otherwise show
        # up as gym raids.
        if is_max_battle(raid):
            continue
        tier_label = raid.get("tier_raw") or raid.get("tier", "")
        if not is_tier_five_or_higher(tier_label):
            continue
        entry = _build_entry(raid, now, local_tz)
        if entry is None:
            continue
        (active if entry["state"] == "active" else upcoming).append(entry)
    return _sorted_entries(active, upcoming)


def load_max_battles(path=None):
    """Max Battles, newest-expiring first, standing rotation last.

    Tiers 5 and 6 get dated windows from breakingNews; tiers 1-4 are the
    permanent Power-Spot rotation and carry no schedule at all.
    """
    now = datetime.now(UTC)
    local_tz = _source_tz()
    scheduled = []
    standing = []
    for raid in _read_raid_data(path):
        if not is_max_battle(raid):
            continue
        entry = _build_entry(raid, now, local_tz)
        if entry is None:
            continue
        (scheduled if (entry["start"] or entry["end"]) else standing).append(entry)
    active = [e for e in scheduled if e["state"] == "active"]
    upcoming = [e for e in scheduled if e["state"] == "upcoming"]
    standing.sort(key=lambda item: (item.get("tier") or "", item.get("pokemon") or ""))
    return _sorted_entries(active, upcoming) + standing


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_tier_five_or_higher(tier_label):
    if not tier_label:
        return False
    tier_label = tier_label.upper()
    if "MEGA" in tier_label:
        return True
    for num in range(5, 8):
        if f"RAID_LEVEL_{num}" in tier_label or f"TIER {num}" in tier_label:
            return True
    digits = ''.join(ch for ch in tier_label if ch.isdigit())
    if digits and digits.isdigit():
        return int(digits) >= 5
    return False


def humanize_schedule(now, start, end):
    if start and start > now:
        diff_hours = (start - now).total_seconds() / 3600
        duration_suffix = ""
        if end and end > start:
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours < 24:
                dur_h = max(1, round(duration_hours))
                duration_suffix = f" for {dur_h}h"
        if diff_hours <= 0:
            return "Starts soon" + duration_suffix
        if diff_hours >= 24:
            days = math.ceil(diff_hours / 24)
            return f"Starts in {days} day{'s' if days != 1 else ''}" + duration_suffix
        hours = math.ceil(diff_hours)
        return f"Starts in {hours} hour{'s' if hours != 1 else ''}" + duration_suffix
    if end and end > now:
        diff_hours = (end - now).total_seconds() / 3600
        if diff_hours <= 0:
            return "Ends soon"
        if diff_hours >= 24:
            days = math.ceil(diff_hours / 24)
            return f"{days} more day{'s' if days != 1 else ''}"
        hours = math.ceil(diff_hours)
        return f"{hours} more hour{'s' if hours != 1 else ''}"
    return "Schedule unknown"


def humanize_tier_label(tier_label):
    label = (tier_label or "").upper()
    # Max first, and before the MEGA test: "_MAX" contains no "MEGA", but
    # RAID_LEVEL_6_MAX must not come out as a plain "Tier 6".
    if "_MAX" in label:
        if "RAID_LEVEL_6" in label:
            return "Gigantamax"
        for num in range(1, 8):
            if f"RAID_LEVEL_{num}" in label:
                return f"Max {num}"
        return "Max"
    if "SHADOW" in label:
        base = "Shadow"
    elif "MEGA" in label:
        base = "Mega"
    elif "ULTRA" in label:
        base = "Ultra Beast"
    elif "ELITE" in label:
        base = "Elite"
    else:
        base = "Tier"
    number = ""
    for num in range(1, 8):
        if f"{num}" in label:
            number = str(num)
            break
    return f"{base} {number}".strip()


def format_difficulty_label(value):
    if value is None:
        return "", None
    num = None
    try:
        num = math.ceil(float(value))
    except (ValueError, TypeError):
        num = None
    if num and num > 0:
        return f"{num}+ trainers", num
    # Legacy scraped strings like "10+ trainers" — extract the number
    text = str(value).strip()
    if not text:
        return "", None
    m = re.match(r"(\d+)\+?\s*trainers", text, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        return f"{num}+ trainers", num
    return "", None


def classify_tier_badge(tier_label):
    label = (tier_label or "").upper()
    # Before the MEGA test, same reason as in humanize_tier_label().
    if "_MAX" in label:
        return "tier-max"
    if "SHADOW" in label:
        return "tier-shadow"
    if "MEGA" in label:
        return "tier-mega"
    return "tier-legendary"


def difficulty_class(level):
    if level is None:
        return "difficulty-unknown"
    if level < 3:
        return "difficulty-easy"
    if level == 3:
        return "difficulty-medium"
    if level == 4:
        return "difficulty-warning"
    if level == 5:
        return "difficulty-hard"
    return "difficulty-extreme"


WATCHDOG_INSTANCE_NAME = "pogo-raid-counters"
WATCHDOG_VERSION = os.environ.get("APP_VERSION", "dev")
WATCHDOG_MAX_DATA_AGE_SECONDS = 30 * 3600  # cron is daily at 03:00 UTC; 30h gives one retry window
WATCHDOG_MIN_FREE_BYTES = 100 * 1024 * 1024  # 100 MB


def _run_check(fn):
    try:
        return fn()
    except Exception as exc:
        return f"ERROR: {exc}"


def _watchdog_data_path():
    return os.environ.get("RAID_DATA_PATH") or "/data/available_raids.json"


def _check_raid_data():
    path = _watchdog_data_path()
    if not os.path.exists(path):
        return f"ERROR: file missing at {path}"
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        return f"ERROR: expected list, got {type(data).__name__}"
    return f"OK ({len(data)} entries)"


def _check_raid_data_age():
    path = _watchdog_data_path()
    if not os.path.exists(path):
        return f"ERROR: file missing at {path}"
    age = time.time() - os.path.getmtime(path)
    age_h = int(age // 3600)
    if age > WATCHDOG_MAX_DATA_AGE_SECONDS:
        return f"ERROR: {age_h}h old (cron likely failed)"
    return f"OK ({age_h}h old)"


def _check_active_raids():
    raids = load_available_raids()
    if not raids:
        return "WARNING: no tier 5+ raids loaded"
    return f"OK ({len(raids)} active/upcoming)"


def _check_disk_space():
    path = os.path.dirname(_watchdog_data_path()) or "/"
    if not os.path.exists(path):
        path = "/"
    stat = os.statvfs(path)
    free = stat.f_frsize * stat.f_bavail
    if free < WATCHDOG_MIN_FREE_BYTES:
        return f"ERROR: {free // (1024 * 1024)}MB free at {path}"
    return f"OK ({free // (1024 * 1024)}MB free)"


def watchdog_response(start_response):
    checks = {
        "raid_data": _run_check(_check_raid_data),
        "raid_data_age": _run_check(_check_raid_data_age),
        "active_raids": _run_check(_check_active_raids),
        "disk_space": _run_check(_check_disk_space),
    }
    overall = "ERROR" if any(v.startswith("ERROR") for v in checks.values()) else "OK"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    body = (
        f"status: {overall}\n"
        f"name: {WATCHDOG_INSTANCE_NAME}\n"
        f"version: {WATCHDOG_VERSION}\n"
        f"time: {now}\n"
        + "\n".join(f"{k}: {v}" for k, v in checks.items())
        + "\n"
    )
    encoded = body.encode("utf-8")
    start_response('200 OK', [
        ('Content-Type', 'text/plain; charset=utf-8'),
        ('Content-Length', str(len(encoded))),
        ('Cache-Control', 'no-store'),
    ])
    return [encoded]


def build_effectiveness(raid_type1, raid_type2=None):
    """Effectiveness payload for one or two boss types (JSON-serializable)."""
    effective, double, resisting = calculate_effectiveness(raid_type1, raid_type2 or None)
    types = [raid_type1] + ([raid_type2] if raid_type2 else [])
    return {
        "types": types,
        "effective_attackers": effective,
        "double_effective_attackers": double,
        "resisting_attackers": resisting,
        "search_string": generate_search_string(effective),
        "double_search_string": generate_search_string(double) if double else "",
    }


def _data_updated_at():
    path = _watchdog_data_path()
    if not os.path.exists(path):
        return None
    return datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat()


def build_raids_payload(state_filter=None, loader=None, key="raids"):
    """Bosses enriched with effective attackers + search string.

    `loader` selects the mode: gym raids by default, Max Battles when
    load_max_battles is passed. The item shape is identical so a consumer can
    treat both lists the same, except that a Max Battle never carries a
    trainer count -- see populate_estimators() in availableraids.py.
    """
    items = []
    for raid in (loader or load_available_raids)():
        state = raid.get("state")
        if state_filter and state != state_filter:
            continue
        boss_types = [t for t in (raid.get("types") or []) if t in pokemon_types]
        eff = None
        if boss_types:
            t2 = boss_types[1] if len(boss_types) > 1 else None
            eff = build_effectiveness(boss_types[0], t2)
        items.append({
            "pokemon": raid.get("pokemon"),
            "tier": raid.get("tier"),
            "state": state,
            "status": raid.get("status"),
            "start": raid["start"].isoformat() if raid.get("start") else None,
            "end": raid["end"].isoformat() if raid.get("end") else None,
            "types": raid.get("types", []),
            "difficulty": raid.get("difficulty") or None,
            "difficulty_level": raid.get("difficulty_level"),
            "max_battle": bool(raid.get("max_battle")),
            "counters": raid.get("counters") or [],
            "url": raid.get("url"),
            "effective_attackers": eff["effective_attackers"] if eff else [],
            "double_effective_attackers": eff["double_effective_attackers"] if eff else [],
            "search_string": eff["search_string"] if eff else "",
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_updated_at": _data_updated_at(),
        "count": len(items),
        key: items,
    }


API_HELP = {
    "endpoints": {
        "/api/raids": (
            "Current tier 5+ raids (active + upcoming ~3 days). Each raid includes its "
            "types, the effective attacker types, and an in-game search string. "
            "Optional ?state=active or ?state=upcoming."
        ),
        "/api/maxbattles": (
            "Current Max Battles at Power Spots, same shape as /api/raids. Tiers 5 "
            "and 6 carry a dated window, tiers 1-4 are the standing rotation and have "
            "none. Never carries a trainer count. Optional ?state=active or ?state=upcoming."
        ),
        "/api/effectiveness/<type>": "Effective attackers against a single boss type.",
        "/api/effectiveness/<type1>/<type2>": "Effective attackers against a dual-type boss.",
    },
    "types": sorted(pokemon_types),
}


ICON_DIR = os.environ.get("RAID_ICON_DIR") or "/data/icons"

# Deliberately strict rather than clever: the mirror writes exactly this shape
# (availableraids.mirrored_icon_name), so anything else is not ours. No
# os.path.join with user input, no normalisation to reason about, no way to
# express a traversal in the first place.
ICON_NAME_RE = re.compile(r"\A[A-Za-z0-9._-]+\.png\Z")


def icon_response(start_response, name):
    """Serve a mirrored boss icon from the data volume."""
    if not ICON_NAME_RE.match(name or "") or ".." in name:
        start_response('404 Not Found', [('Content-Type', 'text/plain; charset=utf-8')])
        return [b'not found']
    path = os.path.join(ICON_DIR, name)
    try:
        with open(path, 'rb') as fp:
            blob = fp.read()
    except OSError:
        start_response('404 Not Found', [('Content-Type', 'text/plain; charset=utf-8')])
        return [b'not found']
    start_response('200 OK', [
        ('Content-Type', 'image/png'),
        ('Content-Length', str(len(blob))),
        # The filename encodes the asset, and Niantic does not reuse one for
        # different artwork, so this can be cached hard.
        ('Cache-Control', 'public, max-age=2592000, immutable'),
    ])
    return [blob]


def _json_response(start_response, payload, status='200 OK'):
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    start_response(status, [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(encoded))),
        ('Cache-Control', 'no-store'),
        ('Access-Control-Allow-Origin', '*'),
    ])
    return [encoded]


def api_response(start_response, path_parts, params):
    """Read-only JSON API. `path_parts` excludes the leading 'api' segment."""
    if not path_parts:
        return _json_response(start_response, API_HELP)
    section = path_parts[0]
    if section == 'pvp' and len(path_parts) > 1 and path_parts[1] == 'index':
        return pvp_index_response(start_response)
    if section in ('raids', 'maxbattles'):
        state = (params.get('state', [''])[0] or '').strip().lower() or None
        if state and state not in {'active', 'upcoming'}:
            return _json_response(
                start_response,
                {"error": "state must be 'active' or 'upcoming'"},
                '400 Bad Request',
            )
        if section == 'maxbattles':
            payload = build_raids_payload(state, loader=load_max_battles, key='max_battles')
            # Said in the payload, not only in the docs: a consumer that sees
            # no difficulty must know it is missing on purpose.
            payload["difficulty_note"] = (
                "Trainer counts come from Pokebattler's precomputed Max Battle table, "
                "not from the raid simulator (which computes _MAX tiers as ordinary "
                "raids and understates them badly). Eternamax Eternatus is excluded "
                "as unobtainable. A Max Battle lobby holds 4 trainers, 100 for "
                "Gigantamax. Bosses missing from the table carry no estimate."
            )
            return _json_response(start_response, payload)
        return _json_response(start_response, build_raids_payload(state))
    if section == 'effectiveness':
        req_types = [t for t in (normalize_type(p) for p in path_parts[1:3]) if t]
        if not req_types:
            return _json_response(
                start_response,
                {
                    "error": "provide one or two raid types, e.g. /api/effectiveness/ghost/dragon",
                    "types": sorted(pokemon_types),
                },
                '400 Bad Request',
            )
        t1 = req_types[0]
        t2 = req_types[1] if len(req_types) > 1 and req_types[1] != t1 else None
        return _json_response(start_response, build_effectiveness(t1, t2))
    return _json_response(
        start_response,
        {"error": f"unknown endpoint '/api/{section}'", **API_HELP},
        '404 Not Found',
    )


PVP_HEAD = (
    '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>PvP-Rechner – Pokémon Go</title>'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">'
)


def pvp_index_response(start_response):
    """Species list for the search box: slug, name, icon. Cacheable.

    Served apart from the page because it is the same ~1660 entries every
    time; inlining it would re-send a hundred kilobytes on every click
    through an evolution line.
    """
    index = pvp.load_pokemon()
    payload = {
        # [slug, English name, icon, German name]. Both names travel so the
        # search box can match either one without a second request.
        "pokemon": [
            [entry["slug"], entry["name"], entry.get("image") or "",
             entry.get("name_de") or ""]
            for entry in sorted(index.values(), key=lambda e: e.get("name") or "")
        ]
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    start_response('200 OK', [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(encoded))),
        # Rebuilt nightly at most, and a stale list only misses a new species.
        ('Cache-Control', 'public, max-age=21600'),
    ])
    return [encoded]


def pvp_response(start_response, path_parts, environ=None, params=None):
    """/pvp, /pvp/<slug> and /pvp/<slug>/<a>-<d>-<s>.

    ?lang=de|en sets the cookie and redirects back to the clean path, so the
    switch survives without JavaScript and the first paint is already in the
    right language -- no flash of the other one.
    """
    environ = environ or {}
    slug = path_parts[0] if path_parts else ''
    iv = pvp.parse_iv_path(path_parts[1]) if len(path_parts) > 1 else (0, 0, 0)

    requested = (params or {}).get('lang', [''])[0]
    if requested:
        lang = pvp.pick_lang(requested)
        target = pvp.PVP_ROUTE + (f"/{slug}" if slug else "")
        if slug and len(path_parts) > 1:
            target += f"/{pvp.iv_path(*iv)}"
        start_response('302 Found', [
            ('Location', target),
            # A year: it is a display preference, not a session.
            ('Set-Cookie',
             (f"{pvp.LANG_COOKIE}={lang}; Path=/; Max-Age=31536000; "
              "SameSite=Lax")),
        ])
        return [b'']

    lang = pvp.choose_lang(environ.get('HTTP_COOKIE'),
                           environ.get('HTTP_ACCEPT_LANGUAGE'))
    index = pvp.load_pokemon()
    body, script = pvp.render_pvp_page(index, slug, iv, lang)
    page = (
        PVP_HEAD.replace('lang="de"', f'lang="{lang}"')
        + '<style>' + pvp.PVP_STYLES + '\n        ' + TYPE_BADGE_STYLES + '</style>'
        + '</head><body><main class="container">'
        + '<nav><ul><li><strong>PvP-Rechner</strong></li></ul>'
        + '<ul><li><a href="/">Raids</a></li></ul></nav>'
        + body
        + '</main>' + script + '</body></html>'
    )
    encoded = page.encode('utf-8')
    start_response('200 OK', [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Content-Length', str(len(encoded))),
        ('X-Content-Type-Options', 'nosniff'),
        ('X-Frame-Options', 'DENY'),
        ('Referrer-Policy', 'strict-origin-when-cross-origin'),
        # The page varies by cookie and carries its own CSS and JS inline, so
        # a heuristically cached copy is a stale *application*, not just a
        # stale number. With no headers at all iOS Safari happily served one
        # for long enough to make a fixed layout look unfixed. no-cache still
        # allows a 304, it just forces the revalidation.
        ('Cache-Control', 'no-cache'),
        ('Vary', 'Cookie, Accept-Language'),
    ])
    return [encoded]


def application(environ, start_response):
    params = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)
    path_info = environ.get('PATH_INFO', '').strip('/')
    if path_info == 'watchdog':
        return watchdog_response(start_response)
    if path_info == 'api' or path_info.startswith('api/'):
        api_parts = [p for p in path_info.split('/') if p][1:]
        return api_response(start_response, api_parts, params)
    if path_info.startswith('icons/'):
        return icon_response(start_response, path_info[len('icons/'):])
    if path_info == 'pvp' or path_info.startswith('pvp/'):
        pvp_parts = [p for p in path_info.split('/') if p][1:]
        return pvp_response(start_response, pvp_parts, environ, params)
    path_parts = [normalize_type(part) for part in path_info.split('/') if part]
    raid_type1 = path_parts[0] if path_parts else ''
    raid_type2 = path_parts[1] if len(path_parts) > 1 else ''

    # Legacy query-param support: redirect to clean path URL
    form_type1 = normalize_type(params.get('raid_type1', [''])[0])
    form_type2 = normalize_type(params.get('raid_type2', [''])[0])

    if form_type1:
        redirect_path = environ.get('SCRIPT_NAME', '')
        redirect_path += f"/{form_type1}"
        if form_type2 and form_type2 != form_type1:
            redirect_path += f"/{form_type2}"
        start_response('302 Found', [('Location', redirect_path)])
        return [b'']

    if not raid_type1 and raid_type2:
        raid_type1, raid_type2 = raid_type2, ''
    elif raid_type1 and raid_type2 and raid_type1 == raid_type2:
        raid_type2 = ''

    body_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '    <title>Pokémon Go Raid Helper</title>',
        '    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">',
        '    <style>',
        '        .type-badge { display: inline-flex; align-items: center; padding: 0.2rem 0.85rem; border-radius: 999px; font-weight: 600; text-transform: capitalize; font-size: 0.95rem; margin: 0 0.35rem 0.35rem 0; }',
        '        .results h1 .type-badge { font-size: inherit; }',
        '        .copy-row { display: flex; gap: 0.5rem; align-items: center; }',
        '        .copy-row textarea { flex: 1; }',
        '        .copy-row button { white-space: nowrap; }',
        '        .raid-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }',
        '        .raid-card { padding: 1rem; border: 1px solid #e0e0e0; border-radius: 0.5rem; text-align: center; }',
        '        .raid-card.upcoming { background-color: #f5f5f5; }',
        '        .raid-badge-row { display: flex; justify-content: center; gap: 0.4rem; margin: 0.35rem 0; flex-wrap: wrap; }',
        '        a.raid-badge-row { gap: 0.15rem; flex-wrap: nowrap; }',
        '        .raid-card .type-badge { font-size: 0.38rem; padding: 0.08rem 0.34rem; margin: 0; }',
        '        .raid-badge { display: inline-flex; align-items: center; padding: 0.2rem 0.8rem; border-radius: 999px; font-weight: 600; font-size: 0.85rem; text-transform: capitalize; }',
        '        .tier-legendary { background-color: #d4af37; color: #1f1f1f; }',
        '        .tier-shadow { background: linear-gradient(120deg, #2c003e, #5a189a); color: #fff; }',
        '        .tier-mega { background: linear-gradient(120deg, #00acc1, #2ec4b6); color: #fff; }',
        # Dynamax red, so a Power-Spot card is never mistaken for a gym raid.
        '        .tier-max { background: linear-gradient(120deg, #c2185b, #e91e63); color: #fff; }',
        '        .difficulty-easy { background-color: #2e7d32; color: #fff; }',
        '        .difficulty-medium { background-color: #66bb6a; color: #1f1f1f; }',
        '        .difficulty-warning { background-color: #ffeb3b; color: #1f1f1f; }',
        '        .difficulty-hard { background-color: #fb8c00; color: #1f1f1f; }',
        '        .difficulty-extreme { background-color: #c62828; color: #fff; }',
        '        .difficulty-unknown { background-color: #b0bec5; color: #1f1f1f; }',
        '        .raid-card img { margin: 0 auto 0.5rem; }',
        f'        {TYPE_BADGE_STYLES}',
        '    </style>',
        '</head>',
        '<body>',
        '<main class="container">',
        ('<nav><ul><li><strong>Raid Helper</strong></li></ul>'
         '<ul><li><a href="/pvp">PvP-Rechner</a></li></ul></nav>')
    ]

    raid_list = load_available_raids()
    max_battle_list = load_max_battles()

    if raid_type1:
        (effective_attackers, double_attackers, resisting_attackers) = calculate_effectiveness(raid_type1, raid_type2 or None)
        heading_types = [raid_type1] + ([raid_type2] if raid_type2 else [])
        body_parts.append('<section class="results">')
        body_parts.append(render_type_badges('Effective Attackers for Raid Type(s)', heading_types, tag='h1'))
        if effective_attackers:
            search_string = generate_search_string(effective_attackers)
            body_parts.append(render_type_badges('Effective attackers', effective_attackers))
            body_parts.append(render_copy_block('Search string', search_string, 'search-string'))
        else:
            body_parts.append('<p>No effective attackers found.</p>')

        # if resisting_attackers:
        #     body_parts.append(render_type_badges('Resistances', resisting_attackers))

        if double_attackers:
            body_parts.append(render_type_badges('Double effective attackers', double_attackers))
            double_search = generate_search_string(double_attackers)
            body_parts.append(render_copy_block('Double effective', double_search, 'double-search-string'))
        body_parts.append('</section>')

    raid_section_html = render_boss_section(raid_list, "Tier 5+ Raids (Next 3 Days)")
    # Same reasoning as the Tier-5 cut for raids, only stricter: tier 3 and
    # below is comfortably soloable, so a card there helps nobody organise
    # anything. What is left are the ones worth rounding people up for. The
    # full list, all tiers, stays available at /api/maxbattles.
    max_battle_html = render_boss_section(
        [m for m in max_battle_list if max_tier_number(m.get("tier")) >= 4],
        "Max Battles Tier 4+ (Power Spots)",
        note=(
            "Trainer counts come from Pokebattler's own Max Battle table, not "
            "from the raid simulator, and exclude Eternamax Eternatus. A Max "
            "Battle lobby holds 4 trainers (100 for Gigantamax). Bosses too "
            "new for the table show no estimate."
        ),
    )

    script_name = html.escape(environ.get('SCRIPT_NAME', ''))

    body_parts.append(f"""
        <section>
            <h2>Enter Raid Types</h2>
            <form id="raid_form" class="raid-form" onsubmit="return false;">
                <label for="raid_type1">
                    Raid Type 1
                    {generate_dropdown('raid_type1', raid_type1)}
                </label>
                <label for="raid_type2">
                    Raid Type 2 (optional)
                    {generate_dropdown('raid_type2', raid_type2)}
                </label>
                <button type="submit">Submit</button>
            </form>
        </section>
        <section>
            <h2>Quick Pokebattler Lookup</h2>
            <form method="get" action="https://www.google.com/search" target="_blank" id="pokebattler_form">
                <label for="pokebattler_name">
                    Pokémon name
                    <input type="text" id="pokebattler_name" placeholder="e.g. Darkrai" required>
                </label>
                <input type="hidden" name="q" id="pokebattler_query_field" value="">
                <input type="hidden" name="gbv" value="1">
                <button type="submit">Search</button>
            </form>
        </section>
        {raid_section_html}
        {max_battle_html}
    </main>
    """)

    body_parts.append("""
    <script>
    document.addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-copy-target]');
        if (!button) {
            return;
        }
        const targetId = button.getAttribute('data-copy-target');
        const textarea = document.getElementById(targetId);
        if (!textarea) {
            return;
        }
        try {
            await navigator.clipboard.writeText(textarea.value);
            const originalLabel = button.textContent;
            button.textContent = 'Copied!';
            setTimeout(() => {
                button.textContent = originalLabel;
            }, 1500);
        } catch (err) {
            console.error('Copy failed', err);
        }
    });

    const raidForm = document.getElementById('raid_form');
    if (raidForm) {
        raidForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const t1 = document.getElementById('raid_type1').value;
            const t2 = document.getElementById('raid_type2').value;
            let path = '""" + script_name + """';
            if (t1) {
                path += '/' + t1;
                if (t2 && t2 !== t1) {
                    path += '/' + t2;
                }
            }
            window.location.href = path || '/';
        });
    }

    const pokebattlerForm = document.getElementById('pokebattler_form');
    const pokebattlerNameInput = document.getElementById('pokebattler_name');
    const pokebattlerQueryField = document.getElementById('pokebattler_query_field');
    if (pokebattlerForm && pokebattlerNameInput && pokebattlerQueryField) {
        pokebattlerForm.addEventListener('submit', () => {
            const name = pokebattlerNameInput.value.trim();
            pokebattlerQueryField.value = name ? `site:pokebattler.com ${name}` : 'site:pokebattler.com';
        });
    }
    </script>
    </body></html>
    """)

    response_body = ''.join(body_parts)
    response_headers = [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Content-Length', str(len(response_body.encode('utf-8')))),
        ('X-Content-Type-Options', 'nosniff'),
        ('X-Frame-Options', 'DENY'),
        ('Referrer-Policy', 'strict-origin-when-cross-origin'),
    ]
    start_response('200 OK', response_headers)
    return [response_body.encode('utf-8')]


if __name__ == '__main__':
    CGIHandler().run(application)
