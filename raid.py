#!/usr/bin/env python3

import cgi
import cgitb
import html
cgitb.enable()  # Enable debugging for CGI scripts

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
    part1 = [f"@1{attacker}" for attacker in effective_attackers]
    part2_and_3 = [f"@2{attacker},@3{attacker}" for attacker in effective_attackers]
    search_string = f"{','.join(part1)}&{','.join(part2_and_3)}"
    return search_string

# Function to generate dropdown HTML
def generate_dropdown(name, selected_value=None):
    options = ''.join([f'<option value="{ptype}"{" selected" if ptype == selected_value else ""}>{ptype.capitalize()}</option>' for ptype in pokemon_types])
    return f'<select name="{name}"><option value="">--Select--</option>{options}</select>'

# Main function to handle CGI request
def main():
    form = cgi.FieldStorage()
    raid_type1 = html.escape( form.getvalue('raid_type1', '') )
    raid_type2 = html.escape( form.getvalue('raid_type2', '') )

    print("Content-Type: text/html")
    print()
    print("<html><body>")
    print('<meta name="viewport" content="width=device-width, initial-scale=1.0">')

    if raid_type1:
        ( effective_attackers, double_attackers ) = calculate_effectiveness(raid_type1, raid_type2)
        search_string = generate_search_string(effective_attackers)
        print(f"""
            <h1>Effective Attackers for Raid Type(s): {raid_type1.capitalize()} {raid_type2.capitalize() if raid_type2 else ''}</h1>
            <p>Effective attackers: {', '.join(effective_attackers)}</p>
            <p>Search string:<br/><textarea rows=1 style="width:100%;">{search_string}</textarea></p>
        """)
        if double_attackers:
            search_string = generate_search_string(double_attackers)
            print(f"""
            <p>Double effective:<br/><textarea rows=1 style="width:100%;">{search_string}</textarea></p>
            """)
        print("<br><br>")

    print(f"""
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

if __name__ == '__main__':
    main()

