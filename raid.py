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

# Type effectiveness chart
type_effectiveness = {
    "normal": {"rock": 0.625, "ghost": 0.390625, "steel": 0.625},
    "fire": {"fire": 0.625, "water": 0.625, "grass": 1.6, "ice": 1.6, "bug": 1.6, "rock": 0.625, "dragon": 0.625, "steel": 1.6},
    "water": {"fire": 1.6, "water": 0.625, "grass": 0.625, "ground": 1.6, "rock": 1.6, "dragon": 0.625},
    "electric": {"water": 1.6, "electric": 0.625, "grass": 0.625, "ground": 0.390625, "flying": 1.6, "dragon": 0.625},
    "grass": {"fire": 0.625, "water": 1.6, "grass": 0.625, "poison": 0.625, "ground": 1.6, "flying": 0.625, "bug": 0.625, "rock": 1.6, "dragon": 0.625, "steel": 0.625},
    "ice": {"fire": 0.625, "water": 0.625, "grass": 1.6, "ice": 0.625, "ground": 1.6, "flying": 1.6, "dragon": 1.6, "steel": 0.625},
    "fighting": {"normal": 1.6, "ice": 1.6, "poison": 0.625, "flying": 0.625, "psychic": 0.625, "bug": 0.625, "rock": 1.6, "ghost": 0.390625, "dark": 1.6, "steel": 1.6, "fairy": 0.625},
    "poison": {"grass": 1.6, "poison": 0.625, "ground": 0.625, "rock": 0.625, "ghost": 0.625, "steel": 0.390625, "fairy": 1.6},
    "ground": {"fire": 1.6, "electric": 1.6, "grass": 0.625, "poison": 1.6, "flying": 0.390625, "bug": 0.625, "rock": 1.6, "steel": 1.6},
    "flying": {"electric": 0.625, "grass": 1.6, "fighting": 1.6, "bug": 1.6, "rock": 0.625, "steel": 0.625},
    "psychic": {"fighting": 1.6, "poison": 1.6, "psychic": 0.625, "dark": 0.390625, "steel": 0.625},
    "bug": {"fire": 0.625, "grass": 1.6, "fighting": 0.625, "poison": 0.625, "flying": 0.625, "psychic": 1.6, "ghost": 0.625, "dark": 1.6, "steel": 0.625, "fairy": 0.625},
    "rock": {"fire": 1.6, "ice": 1.6, "fighting": 0.625, "ground": 0.625, "flying": 1.6, "bug": 1.6, "steel": 0.625},
    "ghost": {"normal": 0.390625, "psychic": 1.6, "ghost": 1.6, "dark": 0.625},
    "dragon": {"dragon": 1.6, "steel": 0.625, "fairy": 0.390625},
    "dark": {"fighting": 0.625, "psychic": 1.6, "ghost": 1.6, "dark": 0.625, "fairy": 0.625},
    "steel": {"fire": 0.625, "water": 0.625, "electric": 0.625, "ice": 1.6, "rock": 1.6, "steel": 0.625, "fairy": 1.6},
    "fairy": {"fire": 0.625, "fighting": 1.6, "poison": 0.625, "dragon": 1.6, "dark": 1.6, "steel": 0.625}
}

# Function to calculate effectiveness for dual-type raid bosses
def calculate_effectiveness(raid_type1, raid_type2=None):
    effective_attackers = []
    double_attackers = []
    for attacker, defender_dict in type_effectiveness.items():
        effectiveness1 = defender_dict.get(raid_type1, 1)
        effectiveness2 = defender_dict.get(raid_type2, 1) if raid_type2 else 1
        combined_effectiveness = effectiveness1 * effectiveness2
        if combined_effectiveness > 1:
            effective_attackers.append(attacker)
        if combined_effectiveness > 2:
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

    body_parts = [
        '<html><body>',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    ]

    if raid_type1:
        (effective_attackers, double_attackers) = calculate_effectiveness(raid_type1, raid_type2 or None)
        raid_heading = html.escape(raid_type1.capitalize())
        if raid_type2:
            raid_heading += f" {html.escape(raid_type2.capitalize())}"
        body_parts.append(f'<h1>Effective Attackers for Raid Type(s): {raid_heading}</h1>')
        if effective_attackers:
            search_string = generate_search_string(effective_attackers)
            attackers = ', '.join(effective_attackers)
            body_parts.append(f'<p>Effective attackers: {attackers}</p>')
            body_parts.append(f'<p>Search string:<br/><textarea rows="1" style="width:100%;">{search_string}</textarea></p>')
        else:
            body_parts.append('<p>No effective attackers found.</p>')

        if double_attackers:
            double_search = generate_search_string(double_attackers)
            body_parts.append(f'<p>Double effective:<br/><textarea rows="1" style="width:100%;">{double_search}</textarea></p>')
        body_parts.append('<br><br>')

    body_parts.append(f"""
        <h1>Enter Raid Types</h1>
        <form method="get" action="">
            <label for="raid_type1">Raid Type 1:</label>
            {generate_dropdown('raid_type1', raid_type1)}
            <br><br>
            <label for="raid_type2">Raid Type 2 (optional):</label>
            {generate_dropdown('raid_type2', raid_type2)}
            <br><br>
            <input type="submit" value="Submit">
        </form>
    </body></html>
    """)

    response_body = ''.join(body_parts)
    start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(response_body.encode('utf-8'))))])
    return [response_body.encode('utf-8')]


if __name__ == '__main__':
    CGIHandler().run(application)
