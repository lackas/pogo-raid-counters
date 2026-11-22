"""PvP IV ranking: stat products, league caps and evolution families.

Separate from raid.py on purpose. The raid side answers "what is out there and
what beats it"; this side answers "is the thing in my bag worth powering up".
They share only the data volume and the icon mirror.

All of the maths here is deterministic game data: a Pokemon's rank in a league
depends solely on its base stats and the CP cap, never on the live meta. That
is why the page can compute everything in the browser and why this module has
no network calls at all.
"""
import json
import math
import os
import re
from functools import lru_cache

# Combat Power Multiplier per level, from the game master. Verified against the
# published anchors (L1 0.094, L10 0.4225, L20 0.5974, L30 0.7317, L40 0.7903,
# L50 0.8403, L51 0.84530). Levels run to 51: 50 is the normal cap, 51 is Best
# Buddy. The table is a constant of the game and changes at most once a year,
# so it is hardcoded rather than fetched -- a network dependency here would buy
# nothing and could take the page down.
CPM = {
    1: 0.09399999678, 1.5: 0.13513743078, 2: 0.16639786959, 2.5: 0.19265091446,
    3: 0.21573247015, 3.5: 0.23657265503, 4: 0.25572004914, 4.5: 0.27353038110,
    5: 0.29024988413, 5.5: 0.30605738134, 6: 0.32108759880, 6.5: 0.33544503230,
    7: 0.34921267629, 7.5: 0.36245774878, 8: 0.37523558736, 8.5: 0.38759241109,
    9: 0.39956727624, 9.5: 0.41119354952, 10: 0.42250001431, 10.5: 0.43292641341,
    11: 0.44310754538, 11.5: 0.45305995387, 12: 0.46279838681, 12.5: 0.47233607779,
    13: 0.48168495297, 13.5: 0.49085581026, 14: 0.49985843897, 14.5: 0.50870175694,
    15: 0.51739394665, 15.5: 0.52594250877, 16: 0.53435432911, 16.5: 0.54263576223,
    17: 0.55079269409, 17.5: 0.55883059944, 18: 0.56675451994, 18.5: 0.57456914804,
    19: 0.58227890730, 19.5: 0.58988791198, 20: 0.59740000963, 20.5: 0.60482365750,
    21: 0.61215728521, 21.5: 0.61940411057, 22: 0.62656712532, 22.5: 0.63364918162,
    23: 0.64065295458, 23.5: 0.64758096330, 24: 0.65443563461, 24.5: 0.66121926351,
    25: 0.66793400049, 25.5: 0.67458189929, 26: 0.68116492033, 26.5: 0.68768490589,
    27: 0.69414365292, 27.5: 0.70054289328, 28: 0.70688420534, 28.5: 0.71316910233,
    29: 0.71939909458, 29.5: 0.72557561697, 30: 0.73170000315, 30.5: 0.73474101114,
    31: 0.73776948452, 31.5: 0.74078557460, 32: 0.74378943443, 32.5: 0.74678120870,
    33: 0.74976104498, 33.5: 0.75272910531, 34: 0.75568550825, 34.5: 0.75863036652,
    35: 0.76156383753, 35.5: 0.76448606526, 36: 0.76739716530, 36.5: 0.77029727397,
    37: 0.77318650484, 37.5: 0.77606494594, 38: 0.77893275023, 38.5: 0.78179006481,
    39: 0.78463697433, 39.5: 0.78747358365, 40: 0.79030001163, 40.5: 0.79280395096,
    41: 0.79530000687, 41.5: 0.79780392149, 42: 0.80030000210, 42.5: 0.80280389232,
    43: 0.80529999733, 43.5: 0.80780386346, 44: 0.81029999256, 44.5: 0.81280383490,
    45: 0.81529998779, 45.5: 0.81780380662, 46: 0.82029998302, 46.5: 0.82280377863,
    47: 0.82529997826, 47.5: 0.82780375092, 48: 0.83029997349, 48.5: 0.83280375338,
    49: 0.83530002832, 49.5: 0.83780375593, 50: 0.84030002356, 50.5: 0.84280372903,
    51: 0.84530001879,}

LEVELS = tuple(sorted(CPM))
PLAIN_MAX_LEVEL = 50.0
BUDDY_MAX_LEVEL = 51.0

# key, label, CP cap (0 = uncapped)
LEAGUES = (
    ("little", "Little Cup", 500),
    ("great", "Great League", 1500),
    ("ultra", "Ultra League", 2500),
    ("master", "Master League", 0),
)
LEAGUE_KEYS = tuple(key for key, _label, _cap in LEAGUES)
LEAGUE_BY_KEY = {key: (label, cap) for key, label, cap in LEAGUES}

DEFAULT_DATA_PATH = "/data/pvp_pokemon.json"
IV_VALUES = tuple(range(16))


def combat_power(atk, dfn, sta, iv_a, iv_d, iv_s, cpm):
    """CP as the game computes it: floored, never below 10."""
    value = (atk + iv_a) * math.sqrt(dfn + iv_d) * math.sqrt(sta + iv_s) * cpm * cpm / 10
    return max(10, int(value))


def stat_product(atk, dfn, sta, iv_a, iv_d, iv_s, cpm):
    """Effective attack x defense x HP. HP is floored, the other two are not.

    This is the standard PvP bulk measure: the raw product, not normalised.
    Callers that want a percentage divide by the best product in the table.
    """
    return (atk + iv_a) * cpm * (dfn + iv_d) * cpm * int((sta + iv_s) * cpm)


def best_level(atk, dfn, sta, iv_a, iv_d, iv_s, cap, max_level=PLAIN_MAX_LEVEL):
    """Highest level that stays within the CP cap, as (level, cp).

    Returns None when even level 1 busts the cap -- that is how a Pokemon is
    "too big" for a league. With cap 0 (Master) the answer is always max_level.
    """
    found = None
    for level in LEVELS:
        if level > max_level:
            break
        value = combat_power(atk, dfn, sta, iv_a, iv_d, iv_s, CPM[level])
        if cap and value > cap:
            break
        found = (level, value)
    return found


@lru_cache(maxsize=16)
def rank_table(atk, dfn, sta, cap, max_level=PLAIN_MAX_LEVEL):
    """All 4096 IV spreads for one species and cap, best stat product first.

    Each row is (stat_product, iv_a, iv_d, iv_s, level, cp). Cached because a
    full table is ~4096 rows of arithmetic and the same species gets asked for
    repeatedly while someone clicks through IVs.
    """
    rows = []
    for iv_a in IV_VALUES:
        for iv_d in IV_VALUES:
            for iv_s in IV_VALUES:
                best = best_level(atk, dfn, sta, iv_a, iv_d, iv_s, cap, max_level)
                if best is None:
                    continue
                level, value = best
                product = stat_product(atk, dfn, sta, iv_a, iv_d, iv_s, CPM[level])
                rows.append((product, iv_a, iv_d, iv_s, level, value))
    rows.sort(key=lambda row: (-row[0], row[1], row[2], row[3]))
    return rows


def rank_of(rows, iv_a, iv_d, iv_s):
    """Where one spread sits in a rank table: (rank, row, share_of_best).

    rank is 1-based. Returns (None, None, None) when the spread busts the cap
    at every level, which is a legitimate answer for a big species in Little.
    """
    if not rows:
        return (None, None, None)
    best_product = rows[0][0]
    for index, row in enumerate(rows, start=1):
        if row[1] == iv_a and row[2] == iv_d and row[3] == iv_s:
            return (index, row, row[0] / best_product if best_product else 0.0)
    return (None, None, None)


# ---------------------------------------------------------------- species data

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(pokemon_id):
    """KINGAMBIT -> kingambit, NIDORAN_FEMALE -> nidoran-female.

    Used for URLs, so it must be stable: a changed slug breaks every bookmark.
    """
    return SLUG_RE.sub("-", (pokemon_id or "").lower()).strip("-")


def _data_path(path=None):
    return path or os.environ.get("PVP_DATA_PATH") or DEFAULT_DATA_PATH


def load_pokemon(path=None):
    """Read the species dump as {slug: entry}. Missing file yields {}.

    A missing or broken file must never take the page down -- the PvP section
    simply reports that it has no data yet, the way the raid side does.
    """
    try:
        with open(_data_path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    entries = payload.get("pokemon") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return {}
    index = {}
    for entry in entries:
        slug = entry.get("slug") or slugify(entry.get("id"))
        if slug:
            entry["slug"] = slug
            index[slug] = entry
    return index


def search_pokemon(index, query, limit=12):
    """Substring match on name and id, best match first.

    Ranked so that typing "king" puts Kingambit and Kingdra above Slaking:
    a prefix hit beats a hit in the middle, shorter names beat longer ones.
    """
    needle = (query or "").strip().lower()
    if not needle:
        return []
    needle_slug = SLUG_RE.sub("-", needle).strip("-")
    hits = []
    for entry in index.values():
        # Both languages are always searched, whatever the display language
        # is set to. Someone who knows a Pokemon as Glurak should not have to
        # flip a switch before they can type it.
        candidates = [(entry.get("name") or "").lower(),
                      (entry.get("name_de") or "").lower()]
        position = None
        for name in candidates:
            if name and needle in name:
                position = name.index(needle)
                break
        if position is None:
            slug = entry.get("slug") or ""
            if needle_slug and needle_slug in slug:
                position = slug.index(needle_slug)
            else:
                continue
        label = candidates[0] or candidates[1]
        hits.append((0 if position == 0 else 1, position, len(label), label, entry))
    hits.sort(key=lambda hit: hit[:4])
    return [hit[4] for hit in hits[:limit]]


BATTLE_FORM_MARKERS = ("_MEGA", "_GIGANTAMAX", "_PRIMAL")


def _is_battle_form(entry):
    """Mega / Gigantamax / Primal: a temporary state, not an evolution stage."""
    identifier = (entry or {}).get("id") or ""
    return any(marker in identifier for marker in BATTLE_FORM_MARKERS)


def family_chain(index, entry):
    """The evolution line containing `entry`, base form first.

    Built from parentPokemonId rather than familyId alone, because a family can
    branch (Eevee) and only the parent links say which branch a member is on.
    Members off the selected branch are dropped; the caller links to them via
    `family_members` instead.
    """
    if not entry:
        return []
    by_id = {item.get("id"): item for item in index.values()}
    chain = [entry]
    current = entry
    seen = {entry.get("id")}
    while True:                                   # walk down to the base form
        parent_id = current.get("parent")
        parent = by_id.get(parent_id)
        if not parent or parent_id in seen:
            break
        seen.add(parent_id)
        chain.insert(0, parent)
        current = parent
    current = entry
    while True:                                   # and up to the final form
        children = [
            item for item in index.values()
            if item.get("parent") == current.get("id")
            and item.get("id") not in seen
            and not _is_battle_form(item)
        ]
        if not children:
            break
        # Alphabetical order picked "Mega Swampert" over "Swampert" and the
        # chain then skipped the form people actually use. Temporary battle
        # forms are not an evolution step, so they sort last.
        children.sort(key=lambda item: item.get("name") or "")
        child = children[0]
        seen.add(child.get("id"))
        chain.append(child)
        current = child
    return chain


def family_members(index, entry):
    """Every species sharing the family id, for the 'see also' links."""
    if not entry:
        return []
    family = entry.get("family")
    if not family:
        return []
    members = [item for item in index.values() if item.get("family") == family]
    members.sort(key=lambda item: item.get("name") or "")
    return members


# ------------------------------------------------------------------ rendering

PVP_ROUTE = "/pvp"
LANGS = ("de", "en")
DEFAULT_LANG = "de"
LANG_COOKIE = "pvp_lang"


def pick_lang(value):
    """Normalise a cookie or query value to a supported language."""
    value = (value or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def lang_from_accept(header):
    """Best supported language from an Accept-Language header.

    Honours the q-values rather than just taking the first entry, so a
    browser sending "en;q=0.4, de;q=0.9" gets German. Unparsable entries are
    skipped instead of failing the request.
    """
    best, best_q = DEFAULT_LANG, -1.0
    for chunk in (header or "").split(","):
        part, _, params = chunk.strip().partition(";")
        tag = part.strip().lower().split("-")[0]
        if tag not in LANGS:
            continue
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 1.0
        if quality > best_q:
            best, best_q = tag, quality
    return best


def choose_lang(cookie_header, accept_header):
    """Cookie wins; otherwise follow the browser; otherwise German.

    The cookie is an explicit choice by the person and must override what
    their browser happens to advertise -- someone with an English-language
    phone may well want the German names.
    """
    for chunk in (cookie_header or "").split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == LANG_COOKIE and value.strip().lower() in LANGS:
            return value.strip().lower()
    return lang_from_accept(accept_header)


def lang_from_cookies(header):
    """Cookie only, ignoring the browser. Kept for the tests and callers
    that genuinely only care about the stored choice."""
    return choose_lang(header, None)


def named(entry, lang):
    """Display name in the chosen language, falling back to English.

    The fallback matters: ~20 of the newest species have no German string in
    the game's localisation file yet, and an empty name would be worse than
    an English one.
    """
    if lang == "de":
        return (entry or {}).get("name_de") or (entry or {}).get("name") or ""
    return (entry or {}).get("name") or ""
IV_PATH_RE = re.compile(r"\A(\d{1,2})-(\d{1,2})-(\d{1,2})\Z")


def parse_iv_path(part):
    """'0-15-13' -> (0, 15, 13). Anything else -> (0, 0, 0).

    Lenient on purpose: a hand-edited bookmark should land on the page with a
    blank spread rather than a 404.
    """
    match = IV_PATH_RE.match(part or "")
    if not match:
        return (0, 0, 0)
    values = tuple(int(group) for group in match.groups())
    return values if all(0 <= value <= 15 for value in values) else (0, 0, 0)


def iv_path(iv_a, iv_d, iv_s):
    return f"{iv_a}-{iv_d}-{iv_s}"


def _escape(text):
    return (
        str(text or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


PVP_STYLES = """
        .pvp-search { position: relative; margin-bottom: 1rem; }
        .pvp-search input { margin-bottom: 0; }
        .pvp-hits { position: absolute; z-index: 20; left: 0; right: 0; margin: 0;
            padding: 0; list-style: none; background: var(--pico-background-color);
            border: 1px solid var(--pico-muted-border-color); border-radius: 0.4rem;
            max-height: 18rem; overflow-y: auto; }
        .pvp-hits:empty { display: none; }
        .pvp-hits li { display: flex; align-items: center; gap: 0.6rem; padding: 0.3rem 0.6rem;
            cursor: pointer; }
        .pvp-hits li:hover, .pvp-hits li.active { background: var(--pico-primary-focus); }
        .pvp-hits img { width: 32px; height: 32px; object-fit: contain; }
        .pvp-head { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .pvp-head img { width: 72px; height: 72px; object-fit: contain; }
        .pvp-head h2 { margin: 0; }
        .pvp-iv { margin: 0.8rem 0; max-width: 26rem; }
        .pvp-iv-row { margin-bottom: 0.5rem; }
        .pvp-iv-head { display: flex; justify-content: space-between; align-items: baseline;
            margin-bottom: 0.15rem; }
        .pvp-iv-head label { font-weight: 600; margin: 0; font-size: 0.9rem; }
        /* 15 equal columns rather than a flex row: at 390 px a flex row of
           fixed-width dots wrapped after 13 and put 14/15 on a line of their
           own. A grid always fits exactly one row, whatever the width. */
        .pvp-dots { display: grid; grid-template-columns: repeat(15, 1fr); gap: 0.18rem; }
        .pvp-dot { height: 1.9rem; border-radius: 999px; border: 1px solid
            var(--pico-muted-border-color); background: transparent; padding: 0; cursor: pointer;
            font-size: 0.7rem; line-height: 1; color: var(--pico-muted-color); }
        .pvp-dot.on { background: var(--pico-primary); border-color: var(--pico-primary);
            color: var(--pico-primary-inverse); font-weight: 700; }
        .pvp-iv-value { font-variant-numeric: tabular-nums; font-weight: 700;
            font-size: 1.05rem; }
        /* The summary is meant to answer "is this worth keeping" without
           scrolling, so it has to stay inside one phone screen together with
           the header and the dots. Hence the tight tiles. */
        .pvp-summary { margin: 1.4rem 0 2.2rem; }
        .pvp-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
            gap: 0.5rem; }
        .pvp-tile { border: 1px solid var(--pico-muted-border-color); border-left-width: 5px;
            border-radius: 0.4rem; padding: 0.4rem 0.6rem; }
        /* Fixed two-line layout, deliberately without flex-wrap. With
           wrapping, whether the name stayed on the first line depended on
           how wide the rank happened to be, so "#5 Swampert" showed its name
           while "#710" next to it did not -- same markup, different result
           per tile. Rank and name now share line one and never wrap; a long
           name is clipped with an ellipsis instead of pushing anything away.
           The pill moves down to line two next to level and CP. */
        .pvp-tile-head { display: flex; align-items: baseline; gap: 0.4rem;
            line-height: 1.25; min-width: 0; }
        .pvp-tile-rank { font-size: 1.2rem; font-weight: 700; flex: none; }
        .pvp-tile-form { font-weight: 600; min-width: 0; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap; }
        .pvp-tile-meta { display: flex; align-items: center; gap: 0.4rem;
            flex-wrap: wrap; margin-top: 0.25rem; }
        .pvp-tile-line { font-size: 0.8rem; color: var(--pico-muted-color); }
        .pvp-tile-final { box-shadow: inset 0 0 0 1px var(--pico-muted-border-color); }
        .pvp-summary-empty { font-size: 0.9rem; color: var(--pico-muted-color); }
        /* One colour per league, carried by a pill and the tile's left edge.
           Scanning the summary is then a colour match rather than reading
           four similar-looking labels. The hues follow the ones the game and
           the community already use for Great/Ultra/Master. */
        .pvp-pill { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px;
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.02em;
            vertical-align: 0.12em; }
        /* Scoped to .pvp-pill on purpose. These rules also set a text colour,
           and the tile carries the same lg-* class for its left border -- so
           an unscoped .lg-great put color:#fff on the whole tile and the
           Pokemon name went white on white. Only the Ultra tile stayed
           readable, because yellow needs dark text. */
        .pvp-pill.lg-little { background: #2e7d32; color: #fff; }
        .pvp-pill.lg-great  { background: #1565c0; color: #fff; }
        .pvp-pill.lg-ultra  { background: #f9a825; color: #1f1f1f; }
        .pvp-pill.lg-master { background: #6a1b9a; color: #fff; }
        .pvp-tile.lg-little { border-left-color: #2e7d32; }
        .pvp-tile.lg-great  { border-left-color: #1565c0; }
        .pvp-tile.lg-ultra  { border-left-color: #f9a825; }
        .pvp-tile.lg-master { border-left-color: #6a1b9a; }
        .pvp-league { margin-bottom: 2rem; }
        .pvp-league h3 { margin-bottom: 0.5rem; display: flex; align-items: center;
            gap: 0.5rem; flex-wrap: wrap; }
        .pvp-league table { margin-bottom: 0.3rem; }
        .pvp-league td, .pvp-league th { padding: 0.35rem 0.5rem; font-size: 0.92rem; }
        .pvp-rank-top { color: #2e7d32; font-weight: 700; }
        .pvp-rank-good { color: #66bb6a; font-weight: 600; }
        .pvp-rank-meh { color: #b0bec5; }
        .pvp-target { font-weight: 700; }
        .pvp-note { font-size: 0.85rem; color: var(--pico-muted-color); margin: 0.1rem 0 0; }
        .pvp-nofit { color: var(--pico-muted-color); }
        .pvp-lang { text-align: right; margin: -0.4rem 0 0.6rem; font-size: 0.85rem; }
        /* raid.py keeps the base .type-badge rule in its own page styles and
           only shares the per-type colours, so this page was rendering the
           types as plain coloured text with no padding or shape. */
        .type-badge { display: inline-flex; align-items: center;
            padding: 0.15rem 0.7rem; font-weight: 600; text-transform: capitalize;
            font-size: 0.82rem; }
        /* One pill for a dual type: rounded on the outside only, with the two
           halves butted together. Two separate pills read as two unrelated
           tags; this reads as the one thing it is. */
        .pvp-types { display: inline-flex; border-radius: 999px; overflow: hidden;
            margin-top: 0.15rem; }
        .pvp-types .type-badge { border-radius: 0; margin: 0; }
"""


# The whole calculator runs here rather than on the server. Not for load --
# the box is idle -- but for latency: clicking an IV dot must repaint without
# a round trip, and the rank tables depend only on base stats and the cap, so
# they are computed once on load and then only looked up.
# Raw string on purpose. This block is JavaScript that is written out
# verbatim, and a plain """ string would interpret backslash escapes here
# *before* the browser ever sees them. That bit once: a \" meant as a JS
# escape arrived at the browser as a bare ", which closed the surrounding
# string literal and made the whole file a syntax error -- so the search box
# and the IV dots died together, with nothing in the HTML to show for it.
# With r""" what is written is what is served. Prefer single quotes for JS
# strings that contain HTML attributes, so no escaping is needed at all.
PVP_SCRIPT = r"""
(function () {
  "use strict";
  var D = window.PVP_DATA;
  var CPM = D.cpm, LEVELS = D.levels, FAMILY = D.family, LEAGUES = D.leagues;
  var TARGET = D.target, MAXLV = D.maxLevel;

  var T = D.lang === "en" ? {
    cap: " <small>(max %s CP)</small>", nocap: " <small>(no cap)</small>",
    form: "Form", level: "Level", cp: "CP", rank: "Rank", prod: "Stat product",
    nofit: "over the cap, even at level 1",
    ceiling: "Before evolving, at most: ",
    empty: "IV %s: nothing in the top 5 % of any league. Full numbers below."
  } : {
    cap: " <small>(max. %s WP)</small>", nocap: " <small>(ohne Limit)</small>",
    form: "Form", level: "Level", cp: "WP", rank: "Rang", prod: "Statwert",
    nofit: "über dem Limit, auch auf Level 1",
    ceiling: "Vor der Entwicklung höchstens: ",
    empty: "IV %s: nichts in den besten 5 % einer Liga. Vollständige Zahlen unten."
  };

  // The species list is ~1660 entries and identical on every page, so it is
  // fetched once from a cacheable endpoint instead of being inlined into each
  // render. Search simply stays empty until it lands.
  var INDEX = [];
  fetch("/api/pvp/index").then(function (r) { return r.json(); }).then(function (j) {
    INDEX = j.pokemon || [];
  }).catch(function () { /* search degrades to nothing, page still works */ });

  function cp(b, a, d, s, m) {
    return Math.max(10, Math.floor((b.atk + a) * Math.sqrt(b.def + d) *
      Math.sqrt(b.sta + s) * m * m / 10));
  }

  // One table per (species, league). Index is a*256 + d*16 + s, so a spread
  // is a direct array read once this is built.
  function build(b, cap) {
    var n = 4096, sp = new Float64Array(n), lv = new Float32Array(n),
        cv = new Int32Array(n), rank = new Int32Array(n), i, a, d, s, k, m, c, best;
    for (a = 0; a < 16; a++) for (d = 0; d < 16; d++) for (s = 0; s < 16; s++) {
      k = (a << 8) | (d << 4) | s;
      best = -1;
      for (i = 0; i < LEVELS.length; i++) {
        if (LEVELS[i] > MAXLV) break;
        m = CPM[i];
        c = cp(b, a, d, s, m);
        if (cap && c > cap) break;
        best = i;
      }
      if (best < 0) { sp[k] = 0; continue; }   // busts the cap at level 1
      m = CPM[best];
      lv[k] = LEVELS[best];
      cv[k] = cp(b, a, d, s, m);
      sp[k] = (b.atk + a) * m * (b.def + d) * m * Math.floor((b.sta + s) * m);
    }
    var order = [];
    for (i = 0; i < n; i++) if (sp[i] > 0) order.push(i);
    order.sort(function (x, y) { return sp[y] - sp[x]; });
    for (i = 0; i < order.length; i++) rank[order[i]] = i + 1;
    return { sp: sp, lv: lv, cp: cv, rank: rank, count: order.length,
             best: order.length ? sp[order[0]] : 0 };
  }

  var TABLES = {};
  FAMILY.forEach(function (mon) {
    TABLES[mon.slug] = {};
    LEAGUES.forEach(function (lg) { TABLES[mon.slug][lg.key] = build(mon, lg.cap); });
  });

  function cpAtLevel(b, iv, level) {
    var i = LEVELS.indexOf(level);
    return i < 0 ? null : cp(b, iv[0], iv[1], iv[2], CPM[i]);
  }

  function rankClass(rank, count) {
    if (!rank) return "pvp-rank-meh";
    if (rank <= Math.max(10, count * 0.005)) return "pvp-rank-top";
    if (rank <= count * 0.05) return "pvp-rank-good";
    return "pvp-rank-meh";
  }

  function fmtLevel(v) { return v % 1 ? v.toFixed(1) : String(v); }

  // "Worth keeping" cut-off. Top 5% of 4096 is rank 205 -- generous enough
  // that a decent spread shows up, tight enough that the summary stays short.
  var MATCH_SHARE = 0.05;
  // The stage you actually battle with is the last one in the line, so its
  // numbers are always shown even when its rank is unremarkable -- looking up
  // Mudkip almost always means wanting the Swampert values. Little Cup is the
  // exception where an early stage is the point, and that still surfaces via
  // the ordinary top-5% rule.
  var FINAL = FAMILY.length ? FAMILY[FAMILY.length - 1].slug : null;
  // Rows cover the selected stage and everything above it. There is no way
  // to un-evolve, so a Swampert page listing Mudkip's rank is noise.
  var USABLE = FAMILY.slice(D.targetIndex || 0);
  // The stages below it still matter, but only as a ceiling: this is what
  // the Pokemon in your bag may show *before* you evolve it.
  var EARLIER = FAMILY.slice(0, D.targetIndex || 0);

  // Little Cup takes Pokemon that can still evolve and never have -- so the
  // base form of a line that has one, and nothing else. Swampert was being
  // ranked in a cup it cannot enter, which is worse than unhelpful.
  function littleEligible(mon) {
    return FAMILY.length > 1 && mon === FAMILY[0];
  }

  function eligible(mon, lg) {
    return lg.key !== "little" || littleEligible(mon);
  }

  function render(iv) {
    var key = (iv[0] << 8) | (iv[1] << 4) | iv[2];
    var out = [], matches = [];
    LEAGUES.forEach(function (lg) {
      var rows = [], targetLevel = null;
      // Detail tables show the whole line again: there is room once you are
      // scrolling, and seeing where the earlier stages land is useful
      // context. The summary above stays limited to the selected stage and
      // up, because that is the part meant to be read at a glance.
      FAMILY.forEach(function (mon) {
        if (!eligible(mon, lg)) return;
        var t = TABLES[mon.slug][lg.key];
        var fits = t.sp[key] > 0;
        var isFinal = mon.slug === FINAL;
        var usable = USABLE.indexOf(mon) >= 0;
        if (fits && usable && (isFinal || t.rank[key] <= t.count * MATCH_SHARE)) {
          matches.push({ mon: mon, lg: lg, rank: t.rank[key], count: t.count,
                         lv: t.lv[key], cp: t.cp[key], isFinal: isFinal,
                         cls: rankClass(t.rank[key], t.count) });
        }
        if (mon.slug === TARGET && fits) targetLevel = t.lv[key];
        var name = mon.slug === TARGET
          ? '<span class="pvp-target">' + mon.name + "</span>"
          : '<a href="/pvp/' + mon.slug + "/" + iv.join("-") + '">' + mon.name + "</a>";
        if (!fits) {
          rows.push("<tr><td>" + name +
            '</td><td colspan="4" class="pvp-nofit">' + T.nofit + "</td></tr>");
          return;
        }
        var share = t.best ? (t.sp[key] / t.best * 100) : 0;
        rows.push("<tr><td>" + name + "</td><td>" + fmtLevel(t.lv[key]) + "</td><td>" +
          t.cp[key] + '</td><td class="' + rankClass(t.rank[key], t.count) + '">#' +
          t.rank[key] + "</td><td>" + share.toFixed(2) + "%</td></tr>");
      });

      // The point of the whole page: at the level the SELECTED form needs,
      // what CP does each earlier stage show? That is the number you watch
      // while powering up, before the evolution pushes you over the cap.
      // The number you actually watch while powering up: how far the
      // pre-evolution in your bag may go before evolving busts the cap.
      var note = "";
      if (targetLevel !== null && EARLIER.length) {
        var parts = EARLIER.map(function (mon) {
          var c = cpAtLevel(mon, iv, targetLevel);
          return mon.name + " " + (c === null ? "?" : c) + " " + T.cp;
        });
        note = '<p class="pvp-note">' + T.ceiling + parts.join(" · ") +
          " <small>(L" + fmtLevel(targetLevel) + ")</small></p>";
      }

      if (!rows.length) return;   // nobody in the line may enter this cup
      out.push('<section class="pvp-league"><h3><span class="pvp-pill lg-' + lg.key +
        '">' + lg.label + "</span>" +
        (lg.cap ? T.cap.replace("%s", lg.cap) : T.nocap) +
        "</h3><table><thead><tr><th>" + T.form + "</th><th>" + T.level + "</th><th>" +
        T.cp + "</th><th>" + T.rank + "</th><th>" + T.prod +
        "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>" +
        note + "</section>");
    });
    var target = document.getElementById("pvp-results");
    if (target) target.innerHTML = out.join("");
    renderSummary(matches, iv);
  }

  // Shown above the detail tables so the answer to "is this one worth it"
  // fits on the first screen; the full breakdown is a scroll away. Only
  // actual hits are listed -- a bad spread gets one quiet line instead of a
  // wall of mediocre numbers.
  function renderSummary(matches, iv) {
    var box = document.getElementById("pvp-summary");
    if (!box) return;
    if (!matches.length) {
      box.innerHTML = '<p class="pvp-summary-empty">' +
        T.empty.replace("%s", iv.join("/")) + "</p>";
      return;
    }
    // Final stage first, in league order, then everything else by percentile.
    matches.sort(function (a, b) {
      if (a.isFinal !== b.isFinal) return a.isFinal ? -1 : 1;
      if (a.isFinal) return LEAGUES.indexOf(a.lg) - LEAGUES.indexOf(b.lg);
      return (a.rank / a.count) - (b.rank / b.count) || a.rank - b.rank;
    });
    var tiles = matches.slice(0, 8).map(function (m) {
      // Rank and league pill share the first line: they are the two things
      // being scanned for, and stacking them left a hole in every tile.
      // Rank, name and league pill share one line; the numbers go under it.
      // Two lines per tile, no blank row in the middle.
      return '<div class="pvp-tile lg-' + m.lg.key +
        (m.isFinal ? " pvp-tile-final" : "") + '">' +
        '<div class="pvp-tile-head"><span class="pvp-tile-rank ' + m.cls + '">#' +
        m.rank + '</span><span class="pvp-tile-form">' + m.mon.name + "</span></div>" +
        '<div class="pvp-tile-meta"><span class="pvp-pill lg-' + m.lg.key + '">' +
        m.lg.label + '</span><span class="pvp-tile-line">L' + fmtLevel(m.lv) +
        " · " + m.cp + " " + T.cp + "</span></div></div>";
    }).join("");
    box.innerHTML = '<div class="pvp-tiles">' + tiles + "</div>";
  }

  // ---- IV dots: one click per stat, clicking the lit dot again clears to 0.
  var iv = D.iv.slice();

  function paint() {
    [0, 1, 2].forEach(function (slot) {
      var row = document.querySelector('[data-slot="' + slot + '"]');
      if (!row) return;
      row.querySelectorAll(".pvp-dot").forEach(function (dot) {
        dot.classList.toggle("on", Number(dot.dataset.value) <= iv[slot]);
      });
      var value = row.parentNode.querySelector(".pvp-iv-value");
      if (value) value.textContent = iv[slot];
    });
    render(iv);
    var url = "/pvp/" + TARGET + "/" + iv.join("-");
    if (window.history.replaceState) window.history.replaceState(null, "", url);
  }

  // Guarded: /pvp without a species renders the search box only, with no dot
  // rows at all. Attaching blindly threw a TypeError there and took the
  // search listeners below down with it.
  [0, 1, 2].forEach(function (slot) {
    var row = document.querySelector('[data-slot="' + slot + '"]');
    if (!row) return;
    row.addEventListener("click", function (ev) {
      var dot = ev.target.closest(".pvp-dot");
      if (!dot) return;
      var value = Number(dot.dataset.value);
      iv[slot] = iv[slot] === value ? 0 : value;   // same dot again -> 0
      paint();
    });
  });

  // ---- species search: substring, prefix hits first, picture for confirmation
  var box = document.getElementById("pvp-q"), list = document.getElementById("pvp-hits");
  var active = -1, shown = [];

  function search(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    var hits = [];
    for (var i = 0; i < INDEX.length; i++) {
      // Entry is [slug, English name, icon, German name]. Both names are
      // matched regardless of the display language.
      var en = (INDEX[i][1] || "").toLowerCase();
      var de = (INDEX[i][3] || "").toLowerCase();
      var pos = en.indexOf(q);
      if (pos < 0) pos = de.indexOf(q);
      if (pos < 0) continue;
      hits.push([pos === 0 ? 0 : 1, pos, en.length, INDEX[i]]);
      if (hits.length > 400) break;
    }
    hits.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
    return hits.slice(0, 12).map(function (h) { return h[3]; });
  }

  function showHits() {
    shown = search(box.value);
    active = -1;
    list.innerHTML = shown.map(function (e) {
      // Chosen language only -- the other one is matched but never shown.
      var label = D.lang === "de" ? (e[3] || e[1]) : e[1];
      return '<li data-slug="' + e[0] + '"><img loading="lazy" alt="" src="' +
        (e[2] || "") + '"><span>' + label + "</span></li>";
    }).join("");
  }

  function go(slug) { window.location.href = "/pvp/" + slug + "/" + iv.join("-"); }

  box.addEventListener("input", showHits);
  box.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!shown.length) return;
      active = (active + (ev.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      list.querySelectorAll("li").forEach(function (li, i) {
        li.classList.toggle("active", i === active);
      });
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (shown.length) go(shown[active >= 0 ? active : 0][0]);
    } else if (ev.key === "Escape") { list.innerHTML = ""; }
  });
  list.addEventListener("click", function (ev) {
    var li = ev.target.closest("li");
    if (li) go(li.dataset.slug);
  });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest(".pvp-search")) list.innerHTML = "";
  });

  if (FAMILY.length) paint();
})();
"""


def _dots_row(label, slot, value):
    dots = "".join(
        f'<button type="button" class="pvp-dot" data-value="{n}">{n}</button>'
        for n in range(1, 16)
    )
    return (
        '<div class="pvp-iv-row">'
        f'<div class="pvp-iv-head"><label>{label}</label>'
        f'<span class="pvp-iv-value">{value}</span></div>'
        f'<div class="pvp-dots" data-slot="{slot}">{dots}</div>'
        "</div>"
    )


def render_pvp_page(index, slug, iv, lang=DEFAULT_LANG):
    """The calculator page for one species, or the empty search page.

    Everything the browser needs is inlined except the species list, which is
    fetched from /api/pvp/index so it can be cached across page views.
    """
    entry = index.get(slug) if slug else None
    chain = family_chain(index, entry) if entry else []
    relatives = [
        member for member in family_members(index, entry)
        if member not in chain
    ] if entry else []

    levels = [level for level in LEVELS if level <= PLAIN_MAX_LEVEL]
    payload = {
        "lang": lang,
        "levels": levels,
        "cpm": [CPM[level] for level in levels],
        "maxLevel": PLAIN_MAX_LEVEL,
        "target": slug or "",
        "iv": list(iv),
        "leagues": [
            {"key": key, "label": label, "cap": cap} for key, label, cap in LEAGUES
        ],
        # The whole line travels, including stages below the selected one:
        # the rows only show the selected stage and up (there is no way to
        # un-evolve), but the pre-evolutions are still needed to work out the
        # CP ceiling you must stay under before evolving.
        "targetIndex": next(
            (i for i, member in enumerate(chain) if member["slug"] == slug), 0),
        "family": [
            {
                "slug": member["slug"], "name": named(member, lang),
                "atk": member["atk"], "def": member["def"], "sta": member["sta"],
            }
            for member in chain
        ],
    }

    other = "en" if lang == "de" else "de"
    hint = ("Pokémon suchen – Teilname genügt"
            if lang == "de" else
            "Search Pokémon – part of the name is enough")
    parts = [
        '<section class="pvp-search">',
        f'    <input type="search" id="pvp-q" autocomplete="off" placeholder="{hint}">',
        '    <ul class="pvp-hits" id="pvp-hits"></ul>',
        "</section>",
        # A plain link, not a JS toggle: the server sets the cookie and sends
        # you back, so it works on first paint with no flash of the other
        # language and without JavaScript.
        (f'<p class="pvp-lang"><a href="?lang={other}" rel="nofollow">'
         f'{"English names" if other == "en" else "Deutsche Namen"}</a></p>'),
    ]

    if not index:
        parts.append(
            "<p>Keine Artendaten vorhanden. Der naechtliche Lauf schreibt sie "
            "beim naechsten Mal.</p>"
        )
    elif not entry:
        parts.append(
            "<p>Such dir oben ein Pokémon aus. Die Seite rechnet dann für Little, "
            "Great, Ultra und Master durch, welche Stufe sich auf welches Level "
            "bringen lässt – und welche WP die Vorstufen dabei anzeigen.</p>"
            if lang == "de" else
            "<p>Pick a Pokémon above. The page then works out, for Little, Great, "
            "Ultra and Master, which stage can go to which level – and what CP "
            "the pre-evolutions show on the way.</p>"
        )
    else:
        image = entry.get("image") or ""
        badges = "".join(
            f'<span class="type-badge type-{_escape(t)}">{_escape(t)}</span>'
            for t in entry.get("types") or []
        )
        types = f'<span class="pvp-types">{badges}</span>' if badges else ""
        # Only the chosen language is ever displayed. Someone playing the game
        # in English does not want German names alongside, and the reverse
        # holds too -- the switch picks what you see, full stop. Searching
        # still matches both, which costs nothing and is invisible.
        label = named(entry, lang)
        parts.append('<div class="pvp-head">')
        if image:
            parts.append(f'    <img src="{_escape(image)}" alt="{_escape(label)}">')
        parts.append(
            f'    <div><h2>{_escape(label)}</h2>'
            f'<p class="pvp-note">{"Basiswerte" if lang == "de" else "Base stats"} '
            f'{entry["atk"]} / {entry["def"]} / {entry["sta"]}</p>{types}</div>'
        )
        parts.append("</div>")

        parts.append('<div class="pvp-iv">')
        labels = (("Angriff", "Verteidigung", "KP") if lang == "de"
                  else ("Attack", "Defense", "HP"))
        for slot, text in enumerate(labels):
            parts.append(_dots_row(text, slot, iv[slot]))
        parts.append("</div>")
        # Class *and* id: the id is what the script writes into, the class is
        # what the stylesheet targets. It had only the id, so the margin that
        # separates the summary from the league tables silently did nothing.
        parts.append('<div id="pvp-summary" class="pvp-summary"></div>')
        parts.append('<div id="pvp-results"></div>')

        if relatives:
            links = " · ".join(
                f'<a href="{PVP_ROUTE}/{_escape(m["slug"])}/{iv_path(*iv)}">'
                f'{_escape(named(m, lang))}</a>'
                for m in relatives
            )
            intro = ("Weitere Formen dieser Familie" if lang == "de"
                     else "Other forms in this family")
            parts.append(f'<p class="pvp-note">{intro}: {links}</p>')

    script = (
        "<script>window.PVP_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script><script>"
        + PVP_SCRIPT
        + "</script>"
    )
    return "\n".join(parts), script
