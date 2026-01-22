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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAID_DATA_PATH` | `/data/available_raids.json` | Path to raid data JSON file |
| `RAID_SOURCE_TZ` | `America/Los_Angeles` | Timezone for parsing raid schedules |
