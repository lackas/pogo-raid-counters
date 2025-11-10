#!/usr/bin/env python3

import html
import json
import math
import os
from datetime import datetime, timezone
from urllib.parse import parse_qs
from wsgiref.handlers import CGIHandler

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
    return (
        f'<label for="{element_id}">{label_text}</label>'
        f'<div class="copy-row">'
        f'<textarea id="{element_id}" rows="1" readonly>{escaped_content}</textarea>'
        f'<button type="button" class="secondary outline" data-copy-target="{element_id}">Copy</button>'
        f'</div>'
    )


def render_type_badges(label_text, types):
    if not types:
        return f'<p>{label_text}: None</p>'
    badges = ''.join([f'<span class="type-badge type-{ptype}">{ptype.capitalize()}</span>' for ptype in types])
    return f'<p>{label_text}: {badges}</p>'

# Ensure only canonical type names are used when rendering output
def normalize_type(value):
    value = (value or '').strip().lower()
    return value if value in pokemon_types else ''


def load_available_raids(path="available_raids.json"):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return []
    now = datetime.now(timezone.utc)
    active = []
    upcoming = []
    for raid in data:
        tier_label = raid.get("tier_raw") or raid.get("tier", "")
        if not is_tier_five_or_higher(tier_label):
            continue
        start = parse_timestamp(raid.get("start_utc"))
        end = parse_timestamp(raid.get("end_utc"))
        diff_text, diff_value = format_difficulty_label(raid.get("difficulty"))
        entry = {
            "pokemon": raid.get("pokemon", "Unknown"),
            "image": raid.get("image"),
            "url": raid.get("pokebattler_url"),
            "tier": humanize_tier_label(tier_label or raid.get("tier", "")),
            "tier_class": classify_tier_badge(tier_label or raid.get("tier", "")),
            "start": start,
            "end": end,
            "status": humanize_schedule(now, start, end),
            "difficulty": diff_text,
            "difficulty_level": diff_value,
            "state": "active" if start and start <= now else "upcoming"
        }
        (active if entry["state"] == "active" else upcoming).append(entry)
    active.sort(key=lambda item: item.get("end") or datetime.max.replace(tzinfo=timezone.utc))
    upcoming.sort(key=lambda item: item.get("start") or datetime.max.replace(tzinfo=timezone.utc))
    return active + upcoming


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
        if diff_hours <= 0:
            return "Starts soon"
        if diff_hours >= 24:
            days = math.ceil(diff_hours / 24)
            return f"Starts in {days} day{'s' if days != 1 else ''}"
        hours = math.ceil(diff_hours)
        return f"Starts in {hours} hour{'s' if hours != 1 else ''}"
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
        num = int(float(value))
    except (ValueError, TypeError):
        num = None
    if num and num > 0:
        return f"{num}+ trainers", num
    text = str(value).strip()
    if not text:
        return "", None
    if not text.endswith("+ trainers"):
        text = f"{text}+ trainers"
    return text, num


def classify_tier_badge(tier_label):
    label = (tier_label or "").upper()
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


def application(environ, start_response):
    params = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)
    raid_type1 = normalize_type(params.get('raid_type1', [''])[0])
    raid_type2 = normalize_type(params.get('raid_type2', [''])[0])

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
        '        .copy-row { display: flex; gap: 0.5rem; align-items: center; }',
        '        .copy-row textarea { flex: 1; }',
        '        .copy-row button { white-space: nowrap; }',
        '        .raid-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }',
        '        .raid-card { padding: 1rem; border: 1px solid #e0e0e0; border-radius: 0.5rem; text-align: center; }',
        '        .raid-card.upcoming { background-color: #f5f5f5; }',
        '        .raid-badge-row { display: flex; justify-content: center; gap: 0.4rem; margin: 0.35rem 0; flex-wrap: wrap; }',
        '        .raid-badge { display: inline-flex; align-items: center; padding: 0.2rem 0.8rem; border-radius: 999px; font-weight: 600; font-size: 0.85rem; text-transform: capitalize; }',
        '        .tier-legendary { background-color: #d4af37; color: #1f1f1f; }',
        '        .tier-shadow { background: linear-gradient(120deg, #2c003e, #5a189a); color: #fff; }',
        '        .tier-mega { background: linear-gradient(120deg, #00acc1, #2ec4b6); color: #fff; }',
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
        '<main class="container">'
    ]

    raid_list = load_available_raids()

    if raid_type1:
        (effective_attackers, double_attackers, resisting_attackers) = calculate_effectiveness(raid_type1, raid_type2 or None)
        raid_heading = html.escape(raid_type1.capitalize())
        if raid_type2:
            raid_heading += f" {html.escape(raid_type2.capitalize())}"
        body_parts.append('<section class="results">')
        body_parts.append(f'<h1>Effective Attackers for Raid Type(s): {raid_heading}</h1>')
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

    raid_section_html = ""
    if raid_list:
        raid_cards = []
        for raid in raid_list:
            image_html = (
                f'<img src="{html.escape(raid["image"])}" alt="{html.escape(raid["pokemon"])}" style="max-width:100px;display:block;">'
                if raid.get("image") else ''
            )
            link_start = (
                f'<a href="{html.escape(raid["url"])}" target="_blank" rel="noopener">'
                if raid.get("url") else '<span>'
            )
            link_end = '</a>' if raid.get("url") else '</span>'
            card_class = "upcoming" if raid.get("state") == "upcoming" else ""
            tier_badge = f"<span class='raid-badge {raid.get('tier_class', '')}'>{html.escape(raid.get('tier', ''))}</span>" if raid.get("tier") else ""
            difficulty_text = raid.get("difficulty")
            diff_class = difficulty_class(raid.get("difficulty_level"))
            difficulty_badge = (
                f"<span class='raid-badge {diff_class}'>{html.escape(difficulty_text)}</span>"
                if difficulty_text else ""
            )
            badge_row = f"<div class='raid-badge-row'>{tier_badge}{difficulty_badge}</div>"
            raid_cards.append(
                (
                    f"<article class='raid-card {card_class}'>"
                    f"{image_html}{link_start}<strong>{html.escape(raid['pokemon'])}</strong>{link_end}"
                    f"{badge_row}<p>{raid['status']}</p></article>"
                )
            )
        raid_section_html = """
        <section>
            <h2>Tier 5+ Raids (Next 3 Days)</h2>
            <div class="raid-grid">
        """ + ''.join(raid_cards) + """</div></section>
        """

    body_parts.append(f"""
        <section>
            <h2>Enter Raid Types</h2>
            <form method="get" action="" class="raid-form">
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
    start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(response_body.encode('utf-8'))))])
    return [response_body.encode('utf-8')]


if __name__ == '__main__':
    CGIHandler().run(application)
