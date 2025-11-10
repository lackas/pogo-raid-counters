#!/usr/bin/env python3

import html
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
    for attacker, defender_dict in type_effectiveness.items():
        effectiveness1 = defender_dict.get(raid_type1, NEUTRAL)
        effectiveness2 = defender_dict.get(raid_type2, NEUTRAL) if raid_type2 else NEUTRAL
        combined_effectiveness = effectiveness1 * effectiveness2
        if combined_effectiveness > NEUTRAL:
            effective_attackers.append(attacker)
        if combined_effectiveness > DOUBLE_EFFECTIVE_THRESHOLD:
            double_attackers.append(attacker)
    return ( effective_attackers, double_attackers )

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

# Ensure only canonical type names are used when rendering output
def normalize_type(value):
    value = (value or '').strip().lower()
    return value if value in pokemon_types else ''


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
        '</head>',
        '<body>',
        '<main class="container">'
    ]

    if raid_type1:
        (effective_attackers, double_attackers) = calculate_effectiveness(raid_type1, raid_type2 or None)
        raid_heading = html.escape(raid_type1.capitalize())
        if raid_type2:
            raid_heading += f" {html.escape(raid_type2.capitalize())}"
        body_parts.append('<section class="results">')
        body_parts.append(f'<h1>Effective Attackers for Raid Type(s): {raid_heading}</h1>')
        if effective_attackers:
            search_string = generate_search_string(effective_attackers)
            attackers = ', '.join(effective_attackers)
            body_parts.append(f'<p>Effective attackers: {attackers}</p>')
            body_parts.append(f'<label>Search string<textarea rows="1">{search_string}</textarea></label>')
        else:
            body_parts.append('<p>No effective attackers found.</p>')

        if double_attackers:
            double_search = generate_search_string(double_attackers)
            body_parts.append(f'<label>Double effective<textarea rows="1">{double_search}</textarea></label>')
        body_parts.append('</section>')

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
    </main>
    </body></html>
    """)

    response_body = ''.join(body_parts)
    start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(response_body.encode('utf-8'))))])
    return [response_body.encode('utf-8')]


if __name__ == '__main__':
    CGIHandler().run(application)
