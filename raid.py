import argparse

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
    for attacker, defender_dict in type_effectiveness.items():
        effectiveness1 = defender_dict.get(raid_type1, 1)
        effectiveness2 = defender_dict.get(raid_type2, 1) if raid_type2 else 1
        combined_effectiveness = effectiveness1 * effectiveness2
        if combined_effectiveness > 1:
            effective_attackers.append(attacker)
    return effective_attackers

# Function to generate search string
def generate_search_string(effective_attackers):
    search_strings = [f"@{i}{attacker}" for i in range(1, 4) for attacker in effective_attackers]
    return ",".join(search_strings)

# Main function to parse arguments and calculate effective attackers
def main():
    parser = argparse.ArgumentParser(description='Calculate effective attackers for a Pokémon Go raid.')
    parser.add_argument('raid_type1', type=str, help='First type of the raid boss')
    parser.add_argument('raid_type2', type=str, nargs='?', default=None, help='Second type of the raid boss (optional)')

    args = parser.parse_args()

    effective_attackers = calculate_effectiveness(args.raid_type1, args.raid_type2)
    search_string = generate_search_string(effective_attackers)

    print(f"Effective attackers: {effective_attackers}")
    print(f"Search string: {search_string}")

if __name__ == '__main__':
    main()

