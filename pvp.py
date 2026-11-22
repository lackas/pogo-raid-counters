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
        name = (entry.get("name") or "").lower()
        slug = entry.get("slug") or ""
        if needle in name:
            position = name.index(needle)
        elif needle_slug and needle_slug in slug:
            position = slug.index(needle_slug)
        else:
            continue
        hits.append((0 if position == 0 else 1, position, len(name), name, entry))
    hits.sort(key=lambda hit: hit[:4])
    return [hit[4] for hit in hits[:limit]]


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
            if item.get("parent") == current.get("id") and item.get("id") not in seen
        ]
        if not children:
            break
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
        .pvp-iv { margin: 1rem 0; }
        .pvp-iv-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.45rem;
            flex-wrap: wrap; }
        .pvp-iv-row > label { min-width: 5.5rem; font-weight: 600; margin: 0; }
        .pvp-dots { display: flex; gap: 0.22rem; flex-wrap: wrap; }
        .pvp-dot { width: 1.45rem; height: 1.45rem; border-radius: 50%; border: 1px solid
            var(--pico-muted-border-color); background: transparent; padding: 0; cursor: pointer;
            font-size: 0.7rem; line-height: 1; color: var(--pico-muted-color); }
        .pvp-dot.on { background: var(--pico-primary); border-color: var(--pico-primary);
            color: var(--pico-primary-inverse); font-weight: 700; }
        .pvp-iv-value { min-width: 1.8rem; text-align: right; font-variant-numeric: tabular-nums;
            font-weight: 700; }
        .pvp-league { margin-bottom: 1.2rem; }
        .pvp-league h3 { margin-bottom: 0.3rem; }
        .pvp-league table { margin-bottom: 0.3rem; }
        .pvp-league td, .pvp-league th { padding: 0.35rem 0.5rem; font-size: 0.92rem; }
        .pvp-rank-top { color: #2e7d32; font-weight: 700; }
        .pvp-rank-good { color: #66bb6a; font-weight: 600; }
        .pvp-rank-meh { color: #b0bec5; }
        .pvp-target { font-weight: 700; }
        .pvp-note { font-size: 0.85rem; color: var(--pico-muted-color); margin: 0.1rem 0 0; }
        .pvp-nofit { color: var(--pico-muted-color); }
"""


# The whole calculator runs here rather than on the server. Not for load --
# the box is idle -- but for latency: clicking an IV dot must repaint without
# a round trip, and the rank tables depend only on base stats and the cap, so
# they are computed once on load and then only looked up.
PVP_SCRIPT = """
(function () {
  "use strict";
  var D = window.PVP_DATA;
  var CPM = D.cpm, LEVELS = D.levels, FAMILY = D.family, LEAGUES = D.leagues;
  var TARGET = D.target, MAXLV = D.maxLevel;

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

  function render(iv) {
    var key = (iv[0] << 8) | (iv[1] << 4) | iv[2];
    var out = [];
    LEAGUES.forEach(function (lg) {
      var rows = [], targetLevel = null;
      FAMILY.forEach(function (mon) {
        var t = TABLES[mon.slug][lg.key];
        var fits = t.sp[key] > 0;
        if (mon.slug === TARGET && fits) targetLevel = t.lv[key];
        var name = mon.slug === TARGET
          ? '<span class="pvp-target">' + mon.name + "</span>"
          : '<a href="/pvp/' + mon.slug + "/" + iv.join("-") + '">' + mon.name + "</a>";
        if (!fits) {
          rows.push("<tr><td>" + name +
            '</td><td colspan="4" class="pvp-nofit">über dem Limit, auch auf Level 1</td></tr>');
          return;
        }
        var share = t.best ? (t.sp[key] / t.best * 100) : 0;
        rows.push("<tr><td>" + name + "</td><td>" + fmtLevel(t.lv[key]) + "</td><td>" +
          t.cp[key] + '</td><td class="' + rankClass(t.rank[key], t.count) + '">#' +
          t.rank[key] + " <small>/ " + t.count + "</small></td><td>" +
          share.toFixed(2) + "%</td></tr>");
      });

      // The point of the whole page: at the level the SELECTED form needs,
      // what CP does each earlier stage show? That is the number you watch
      // while powering up, before the evolution pushes you over the cap.
      var note = "";
      if (targetLevel !== null && FAMILY.length > 1) {
        var parts = FAMILY.map(function (mon) {
          var c = cpAtLevel(mon, iv, targetLevel);
          return mon.name + " " + (c === null ? "?" : c);
        });
        note = '<p class="pvp-note">Auf Level ' + fmtLevel(targetLevel) +
          " zeigt die Reihe: " + parts.join(" · ") + "</p>";
      }

      out.push('<section class="pvp-league"><h3>' + lg.label +
        (lg.cap ? " <small>(max. " + lg.cap + " WP)</small>" : " <small>(ohne Limit)</small>") +
        "</h3><table><thead><tr><th>Form</th><th>Level</th><th>WP</th><th>Rang</th>" +
        "<th>Statwert</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>" +
        note + "</section>");
    });
    var target = document.getElementById("pvp-results");
    if (target) target.innerHTML = out.join("");
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
      row.parentNode.querySelector(".pvp-iv-value").textContent = iv[slot];
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
      var pos = INDEX[i][1].toLowerCase().indexOf(q);
      if (pos < 0) continue;
      hits.push([pos === 0 ? 0 : 1, pos, INDEX[i][1].length, INDEX[i]]);
      if (hits.length > 400) break;
    }
    hits.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
    return hits.slice(0, 12).map(function (h) { return h[3]; });
  }

  function showHits() {
    shown = search(box.value);
    active = -1;
    list.innerHTML = shown.map(function (e) {
      return '<li data-slug="' + e[0] + '"><img loading="lazy" alt="" src="' +
        (e[2] || "") + '"><span>' + e[1] + "</span></li>";
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
        f"<label>{label}</label>"
        f'<span class="pvp-dots" data-slot="{slot}">{dots}</span>'
        f'<span class="pvp-iv-value">{value}</span>'
        "</div>"
    )


def render_pvp_page(index, slug, iv):
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
        "levels": levels,
        "cpm": [CPM[level] for level in levels],
        "maxLevel": PLAIN_MAX_LEVEL,
        "target": slug or "",
        "iv": list(iv),
        "leagues": [
            {"key": key, "label": label, "cap": cap} for key, label, cap in LEAGUES
        ],
        "family": [
            {
                "slug": member["slug"], "name": member["name"],
                "atk": member["atk"], "def": member["def"], "sta": member["sta"],
            }
            for member in chain
        ],
    }

    parts = [
        '<section class="pvp-search">',
        '    <input type="search" id="pvp-q" autocomplete="off" '
        'placeholder="Pokémon suchen – Teilname genügt, z. B. &quot;king&quot;">',
        '    <ul class="pvp-hits" id="pvp-hits"></ul>',
        "</section>",
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
        )
    else:
        image = entry.get("image") or ""
        types = "".join(
            f'<span class="type-badge type-{_escape(t)}">{_escape(t)}</span>'
            for t in entry.get("types") or []
        )
        parts.append('<div class="pvp-head">')
        if image:
            parts.append(f'    <img src="{_escape(image)}" alt="{_escape(entry["name"])}">')
        parts.append(
            f'    <div><h2>{_escape(entry["name"])}</h2>'
            f'<p class="pvp-note">Basiswerte {entry["atk"]} / {entry["def"]} / '
            f'{entry["sta"]}</p>{types}</div>'
        )
        parts.append("</div>")

        parts.append('<div class="pvp-iv">')
        parts.append(_dots_row("Angriff", 0, iv[0]))
        parts.append(_dots_row("Verteidigung", 1, iv[1]))
        parts.append(_dots_row("KP", 2, iv[2]))
        parts.append("</div>")
        parts.append('<div id="pvp-results"></div>')

        if relatives:
            links = " · ".join(
                f'<a href="{PVP_ROUTE}/{_escape(m["slug"])}/{iv_path(*iv)}">'
                f'{_escape(m["name"])}</a>'
                for m in relatives
            )
            parts.append(
                f'<p class="pvp-note">Weitere Formen dieser Familie: {links}</p>'
            )

    script = (
        "<script>window.PVP_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script><script>"
        + PVP_SCRIPT
        + "</script>"
    )
    return "\n".join(parts), script
