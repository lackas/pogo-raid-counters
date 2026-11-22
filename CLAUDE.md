# CLAUDE.md

## Project Overview

Pokemon Go raid counter helper web app. Calculates type effectiveness against raid bosses and generates in-game search strings for finding counters in your Pokemon storage. Live at https://raid.lackas.net/

## Architecture

- **Pure Python WSGI app** — no web framework, just `wsgiref` and string-built HTML with Pico CSS
- **`raid.py`** — Main web app. Handles routing, type effectiveness calculation, search string generation, and HTML rendering
- **`availableraids.py`** — Fetches current raid data from the Pokebattler JSON APIs the site's own frontend uses (`/raids` for the rotation + `breakingNews` schedule, `/pokemon` for boss types), then per-boss difficulty estimators from the fight simulation API
- **No templates** — HTML is constructed via string concatenation in `raid.py`

## URL Routing

Clean URL paths: `/<type1>` or `/<type1>/<type2>` (e.g., `/water/ghost`). Form submissions redirect to clean URLs via 302.

## JSON API (`/api/...`)

Read-only JSON, no auth (all data is public game data — a token would be friction with no security value, unlike the watchdog which exposes private infra state).

- `GET /api` — endpoint discovery + valid type names
- `GET /api/raids[?state=active|upcoming]` — current tier 5+ raids, each enriched with `types`, `effective_attackers`, `double_effective_attackers`, and a ready-to-paste `search_string`
- `GET /api/maxbattles[?state=active|upcoming]` — Max Battles, same item shape plus `max_battle: true` and a `difficulty_note`. Never carries a trainer count
- `GET /api/effectiveness/<type1>[/<type2>]` — counters for an arbitrary type combo

Implemented in `raid.py`: `build_raids_payload()`, `build_effectiveness()`, `api_response()` (routed from `application()` before the type-path handling). Covered by `smoke_test.py::test_api_raids` / `test_api_effectiveness`.

## PvP IV Calculator (`pvp.py`, `/pvp`)

A second, independent tool on the same app: given a species and an IV spread,
where does it rank in Little / Great / Ultra / Master, and what CP do its
pre-evolutions show on the way there.

- **Routes**: `/pvp`, `/pvp/<slug>`, `/pvp/<slug>/<a>-<d>-<s>`. The IV path is
  what makes a result bookmarkable, and the page rewrites it with
  `history.replaceState` as dots are clicked, so the URL in the bar is always
  the current spread. A malformed IV segment falls back to `0-0-0` rather than
  404 — a hand-edited bookmark should still land somewhere useful.
- **All maths runs in the browser.** Rank tables depend only on base stats and
  the CP cap, never on the live meta, so they are computed once per page load
  (12 tables = 3 family members x 4 leagues) and then only indexed into. An IV
  click must repaint with no round trip. `pvp.py` holds the same algorithm in
  Python for the tests and would serve an API if one is ever wanted.
- **The CPM table is hardcoded** in `pvp.py`, verified against the published
  anchors (L1 0.094, L10 0.4225, L20 0.5974, L30 0.7317, L40 0.7903, L50
  0.8403, L51 0.84530). It is a game constant that changes at most once a
  year; fetching it would add a failure mode for nothing.
- **Why pre-evolution CP is the point.** Powering a Pawniard to *its own*
  Great League ceiling (L50, CP 1466 at 0/15/13) and then evolving gives a
  Kingambit at CP 3827. The binding level is the final form's — L15.5, where
  the Pawniard in your bag still reads CP 574. That number, under each league
  table, is the one you watch while powering up.
- **Species data** comes from the same Pokebattler `/pokemon` blob the raid
  side already fetches (`stats.baseAttack/baseDefense/baseStamina`), dumped to
  `/data/pvp_pokemon.json` by `availableraids.py --pvp-output`. Shadow forms
  are skipped: their base stats are identical, so they would be exact
  duplicates in the rank table and only clutter the search.
- **Evolution lines** are walked through `parentPokemonId`, not `familyId`
  alone, because a family can branch (Eevee). `family_chain()` returns one
  line; everything else in the family is offered as links via
  `family_members()`.
- **The species list is served separately** at `/api/pvp/index` with a 6-hour
  cache, not inlined. It is ~1660 entries / 64 KB and identical on every page;
  inlining it would re-send that on every click through an evolution line.
- **Icon mirroring is budgeted** (`--pvp-icon-budget`, default 400 per run).
  The raid side mirrors ~75 bosses; this one wants ~1660. A few hundred a
  night fills the set in under a week, and an unmirrored entry keeps its
  remote URL meanwhile, so nothing is ever blank.

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
- `RAID_ICON_DIR` — where mirrored boss icons live and are served from (default: `/data/icons`); `--icon-dir ''` disables mirroring
- `PVP_DATA_PATH` — path to the PvP species dump (default: `/data/pvp_pokemon.json`)

## Key Design Decisions

- PoGo-specific type multipliers: 1.6x (super effective), 0.625x (not very effective), 0.390625x (double not very effective)
- Search strings use `@1type` (fast move) and `@2type,@3type` (charge moves) format
- Only Tier 5+ raids are displayed from Pokebattler data (the data file holds the whole rotation; `raid.py` filters)
- **Max Battles are a second, separate section**, never raid cards. They are told apart by the `max_battle` flag (`is_max_battle()` falls back to the tier string for older data files), not by tier — `RAID_LEVEL_5_MAX` and `_6_MAX` both pass `is_tier_five_or_higher()`, and a Power-Spot boss on a raid card sends people to a gym. Tier 6 renders as "Gigantamax".
- The page shows only **Max Battles tier 4 and up**; tier 3 and below is soloable and nobody organises a group for it. All tiers stay in `/api/maxbattles`.
- **Max Battles never take their trainer count from the raid estimator.** That endpoint answers for `_MAX` tiers, but it ignores the Max boss stats: checked 2026-11-14 for Dialga, the raid entry declares `hp 13000` at `cpm 0.7` while the simulation ran `stamina 9080` at level 40 with ordinary charged moves — no Max phases, no Max Move levels. It returned `1.278`, i.e. "2 trainers", for a boss whose lobby holds 4. `populate_estimators()` therefore skips them. Don't "fix" this by re-enabling the call.
- Max Battles in tiers 5/6 get dated windows from `breakingNews`; tiers 1-4 are the standing Power-Spot rotation with **no schedule at all**, so a missing window must not drop them (`build_raid_entries()`) and renders as "Always available"
- Pokebattler lookup uses Google `site:pokebattler.com` search as a workaround
- Difficulty (trainer count) comes from Pokebattler fight simulation API estimator, rounded up via `math.ceil`
- **No HTML scraping.** pokebattler.com became a client-side SPA in October 2026 (the page is a 7 KB shell, `window.REHYDRATE` is gone, boss detail pages render client-side). Everything comes from JSON now; don't reintroduce page parsing.

## Pokebattler Fight API

- Base: `https://fight.pokebattler.com`
- `GET /raids` — `tiers[]` holds the live rotation per tier; `_FUTURE`/`_LEGACY`/`RAID_LEVEL_UNSET` are catalogues and must be skipped, `_MAX` is a different game mode
- `GET /raids` → `breakingNews[]` — the schedule: `startDate`/`endDate` keyed by `(pokemon, tier)`, as epoch ms. With `localTime: true` (the normal case) these are **wall-clock times in California** that apply in each player's own timezone, which is what `RAID_SOURCE_TZ` renders and `raid.py` reads back
- `GET /pokemon` — pokedex (7 MB); `type`/`type2` give boss types without PokeAPI's form-name guesswork
- Estimator path: `attackers[0].randomMove.total.estimator` (NOT `attackers[0].total.estimator`)
- Pokemon slugs use forms like `LUGIA_SHADOW_FORM`, `HO_OH_SHADOW_FORM`, `KYUREM_BLACK_FORM`
- Tier values (e.g. `RAID_LEVEL_5_SHADOW`, `RAID_LEVEL_MEGA_5`) work directly as API path params
- Boss icons: filename table in a hash-named JS chunk, discovered page → `assets/index-*.js` → icon chunk, served under `https://static.pokebattler.com/assets/pokemon/64/`. Strictly best-effort — a failure here must never fail the run. **The chunk moved from `pokebattler-*` to `pokemon-icons-*` around 2026-11-14 and the old one kept 10 stale Mega entries**, so the scrape "succeeded" with 10 entries and every boss silently lost its picture. `fetch_icon_map()` therefore tries all candidates in `ICON_CHUNK_PATTERNS`, keeps the richest table and warns below `MIN_ICON_ENTRIES`. The images are Niantic's own game assets (`pokemon_icon_NNN_00.png`, `pm/pmNNN.fFORM.icon.png`), mirrored by Pokebattler at 64px; the mapping is the only part Pokebattler adds
- **Boss icons are mirrored locally**, served from `/icons/<name>` by `icon_response()` out of `RAID_ICON_DIR`. `mirror_icons()` copies each file once from Pokebattler's 64px CDN during the refresh and never re-fetches; names are flattened (`pm/pm884.icon.png` → `pm_pm884.icon.png`). Not for traffic — the site sees a handful of visits a day — but so a broken icon table leaves the existing pictures in place instead of blanking all 76 at once. `icon_response()` matches an exact whitelist rather than normalising a path.
- Max Battle trainer counts and counters come from a **precomputed JS table**, not an API: page `/max/<any>` → `useMaxData-*.js` → `maxbattles-*.js` → `max-bosses-compact-*.js`, decoded by `_js_object_to_json()` (backtick strings, bare keys). The live calculator (`max-ranking`, `max-battle`) sits behind a JWT and a quota gate — don't try to use it. The table lags the rotation: on 2026-11-14 it matched 49 of 60 live Max bosses and was missing both current tier-5 ones, so a miss is normal and must leave the entry without an estimate rather than blank. `ETERNATUS_ETERNAMAX_FORM` is filtered out as unobtainable — it tops every list by a factor of 3-4 and would make every estimate unreachable in practice. **Tier 6 output is discarded entirely** by `_is_saturated()`: for both Gigantamax bosses three quarters of the counter list sits at 96-99.5, i.e. pinned to a ceiling, and Gigantamax Machamp — the counter every guide names against fighting-weak Duraludon — ranks last at 99.52. The model does not represent a Gigantamax fight (groups of four with Max Guard tanks and Max Spirit healers, not everyone attacking). Tier 4 and 5 spread cleanly and are kept

## Deployment

- `restart.sh` — convenience script: `docker compose down && docker compose up --build -d`
- On container start, `entrypoint.sh` primes raid data if missing or >24h old
- To manually refresh raid data: `docker compose exec raid-web python3 /app/availableraids.py --output /data/available_raids.json`
- Host has no `python` (only `python3`), and no `requests` module outside Docker — test inside container
