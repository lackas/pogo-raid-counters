# Pogo Raid Counters

A web tool for Pokémon GO raiders that calculates type effectiveness against raid bosses and generates search strings for finding counters in your Pokémon storage.

**Live:** https://raid.lackas.net/

## Features

- Calculate effective and double-effective attacking types for any raid boss type combination
- Generate Pokémon GO search strings to filter your storage (e.g., `@1fire,@1rock&@2fire,@3fire`)
- Display current Tier 5+ raids from Pokébattler with difficulty ratings
- Clean URLs: `/water/ghost` for Water/Ghost type boss

## Installation

### Docker (recommended)

```bash
docker compose up -d --build
```

The app runs on port 8000. Raid data is stored in a Docker volume and refreshed daily at 3 AM UTC.

### Local development

```bash
pip install -r requirements.txt
gunicorn -w 2 -b 0.0.0.0:8000 raid:application
```

To fetch raid data manually:

```bash
python availableraids.py --output available_raids.json
export RAID_DATA_PATH=./available_raids.json
```

## JSON API

Read-only JSON endpoints for scripts and agents. Same public data as the HTML
UI, no authentication (the whole site is public).

```
GET /api                                  # endpoint discovery + valid type names
GET /api/raids                            # current tier 5+ raids, each with counters
GET /api/raids?state=active               # only active (or ?state=upcoming)
GET /api/effectiveness/<type>             # counters vs a single boss type
GET /api/effectiveness/<type1>/<type2>    # counters vs a dual-type boss
```

```bash
curl -s https://raid.lackas.net/api/raids | jq '.raids[] | {pokemon, types, effective_attackers}'
curl -s https://raid.lackas.net/api/effectiveness/ghost/dragon
```

`/api/raids` returns each raid with its `types`, the `effective_attackers` and
`double_effective_attackers` types, a ready-to-paste in-game `search_string`,
plus `difficulty`, `state` (`active`/`upcoming`) and `status`. `data_updated_at`
is the age of the underlying scrape (refreshed daily at 3 AM UTC).

```json
{
  "generated_at": "2026-08-21T18:41:05+00:00",
  "data_updated_at": "2026-08-21T03:00:12+00:00",
  "count": 2,
  "raids": [
    {"pokemon": "Giratina", "tier": "Tier 5", "state": "active",
     "status": "9 more days", "types": ["ghost", "dragon"],
     "difficulty": "3+ trainers", "difficulty_level": 3,
     "url": "https://www.pokebattler.com/raids/GIRATINA_ALTERED_FORM",
     "effective_attackers": ["ice", "ghost", "dragon", "dark", "fairy"],
     "double_effective_attackers": [],
     "search_string": "@1ice,@1ghost,...&@2ice,@3ice,..."}
  ]
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAID_DATA_PATH` | `/data/available_raids.json` | Path to raid data JSON file |
| `RAID_SOURCE_TZ` | `America/Los_Angeles` | Timezone for parsing raid schedules |
