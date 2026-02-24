# CLAUDE.md

## Project Overview

Pokemon Go raid counter helper web app. Calculates type effectiveness against raid bosses and generates in-game search strings for finding counters in your Pokemon storage. Live at https://raid.lackas.net/

## Architecture

- **Pure Python WSGI app** — no web framework, just `wsgiref` and string-built HTML with Pico CSS
- **`raid.py`** — Main web app. Handles routing, type effectiveness calculation, search string generation, and HTML rendering
- **`availableraids.py`** — Scraper that fetches current raid data from Pokebattler (parses `window.REHYDRATE` JSON blob + HTML), then fetches per-boss difficulty estimators from the fight simulation API
- **No templates** — HTML is constructed via string concatenation in `raid.py`

## URL Routing

Clean URL paths: `/<type1>` or `/<type1>/<type2>` (e.g., `/water/ghost`). Form submissions redirect to clean URLs via 302.

## Infrastructure

- Docker with gunicorn (2 workers, port 8000)
- Cron job refreshes raid data daily at 3 AM UTC
- Runs as non-root `appuser`
- Connected to external `wtb-shared` Docker network (behind reverse proxy, ports not exposed)
- Raid data stored in Docker volume at `/data/available_raids.json`

## Development

```bash
pip install -r requirements.txt
python availableraids.py --output available_raids.json
RAID_DATA_PATH=./available_raids.json gunicorn -w 2 -b 0.0.0.0:8000 raid:application
```

## Dependencies

- `gunicorn` — WSGI server
- `requests` — HTTP client (used by availableraids.py)

## Linting

Ruff via GitHub Actions on push/PR to main. Run locally: `ruff check .`

## Environment Variables

- `RAID_DATA_PATH` — path to raid data JSON (default: `/data/available_raids.json`)
- `RAID_SOURCE_TZ` — timezone for parsing raid schedules (default: `America/Los_Angeles`)

## Key Design Decisions

- PoGo-specific type multipliers: 1.6x (super effective), 0.625x (not very effective), 0.390625x (double not very effective)
- Search strings use `@1type` (fast move) and `@2type,@3type` (charge moves) format
- Only Tier 5+ raids are displayed from Pokebattler data
- Pokebattler lookup uses Google `site:pokebattler.com` search as a workaround
- Difficulty (trainer count) comes from Pokebattler fight simulation API estimator, rounded up via `math.ceil`

## Pokebattler Fight API

- Base: `https://fight.pokebattler.com`
- Estimator path: `attackers[0].randomMove.total.estimator` (NOT `attackers[0].total.estimator`)
- Pokemon slugs use forms like `LUGIA_SHADOW_FORM`, `HO_OH_SHADOW_FORM`, `KYUREM_BLACK_FORM`
- Tier values from the REHYDRATE blob (e.g. `RAID_LEVEL_5_SHADOW`, `RAID_LEVEL_MEGA_5`) work directly as API path params

## Deployment

- `restart.sh` — convenience script: `docker compose down && docker compose up --build -d`
- On container start, `entrypoint.sh` primes raid data if missing or >24h old
- To manually refresh raid data: `docker compose exec raid-web python3 /app/availableraids.py --output /data/available_raids.json`
- Host has no `python` (only `python3`), and no `requests` module outside Docker — test inside container
