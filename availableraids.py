#!/usr/bin/env python3

"""Fetch current Pokebattler raid data and cache it locally as JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urljoin

import requests

POKEBATTLER_RAIDS_URL = "https://www.pokebattler.com/raids"
DEFAULT_OUTPUT = "available_raids.json"
USER_AGENT = "Mozilla/5.0 (compatible; RaidFetcher/1.0; +https://www.pokebattler.com/)"


class RaidLinkParser(HTMLParser):
    """Collect raid display names, images, and difficulty hints from the HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._current_row: Optional[Dict[str, object]] = None
        self._inside_anchor = False
        self._capture_difficulty = False
        self.results: Dict[str, Dict[str, Optional[str]]] = {}

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        attrs_dict = {name.lower(): value for name, value in attrs}
        if tag == "tr":
            self._current_row = {
                "slug": None,
                "title": None,
                "text": [],
                "image": None,
                "_image_priority": -1,
                "difficulty": None,
            }
        elif self._current_row is not None:
            if tag == "a":
                href = attrs_dict.get("href", "")
                if href.startswith("/raids/"):
                    slug_path = href.split("/raids/")[1].split("?")[0]
                    if slug_path.startswith("defenders/"):
                        slug_path = slug_path.split("/")[-1]
                    slug = slug_path.split("/")[-1]
                    self._current_row["slug"] = slug
                    self._current_row["title"] = attrs_dict.get("title")
                    self._inside_anchor = True
            elif tag in {"img", "image"}:
                src = (
                    attrs_dict.get("xlink:href")
                    or attrs_dict.get("href")
                    or attrs_dict.get("src")
                )
                if src and "assets/pokemon" in src:
                    priority = 2 if "pokemon_icon" in src else 1
                    if src.startswith("//"):
                        src = f"https:{src}"
                    if priority > self._current_row.get("_image_priority", -1):
                        self._current_row["image"] = src
                        self._current_row["_image_priority"] = priority
            elif tag == "span" and self._current_row.get("difficulty") is None:
                class_attr = attrs_dict.get("class", "")
                if "easyDifficulty" in class_attr or "veryEasyDifficulty" in class_attr:
                    self._capture_difficulty = True

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if not self._current_row:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self._capture_difficulty and self._current_row.get("difficulty") is None:
            self._current_row["difficulty"] = stripped
            self._capture_difficulty = False
            return
        if self._inside_anchor:
            text_list = self._current_row.setdefault("text", [])
            if isinstance(text_list, list):
                text_list.append(stripped)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "a" and self._inside_anchor:
            self._inside_anchor = False
        elif tag == "span" and self._capture_difficulty:
            self._capture_difficulty = False
        elif tag == "tr" and self._current_row is not None:
            slug = self._current_row.get("slug")
            if slug:
                text_bits = self._current_row.get("text") or []
                if isinstance(text_bits, list):
                    name = " ".join(text_bits).strip()
                else:
                    name = ""
                title = (self._current_row.get("title") or "")
                if not name and title.endswith("Counters"):
                    name = title[: -len("Counters")].strip()
                if not name:
                    name = slug.replace("_", " ").title()
                existing = self.results.get(slug)
                if existing:
                    if not existing.get("image") and self._current_row.get("image"):
                        existing["image"] = self._current_row["image"]
                    if not existing.get("difficulty") and self._current_row.get("difficulty"):
                        existing["difficulty"] = self._current_row["difficulty"]
                else:
                    self.results[slug] = {
                        "name": name,
                        "image": self._current_row.get("image"),
                        "difficulty": self._current_row.get("difficulty"),
                    }
            self._current_row = None
            self._inside_anchor = False
            self._capture_difficulty = False


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_html(url: str, session: Optional[requests.Session] = None) -> str:
    requester = session or requests
    response = requester.get(url, timeout=20)
    response.raise_for_status()
    return response.text


def extract_rehydrate_blob(html: str) -> Dict:
    match = re.search(
        r"window\.REHYDRATE=JSON\.parse\(decodeURIComponent\(\"(.*?)\"\)\)",
        html,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Unable to locate REHYDRATE payload in page")
    decoded = unquote(match.group(1))
    return json.loads(decoded)


def extract_display_metadata(html: str) -> Dict[str, Dict[str, Optional[str]]]:
    parser = RaidLinkParser()
    parser.feed(html)
    return parser.results


def humanize_tier(tier: str) -> str:
    tier = tier or ""
    tier_upper = tier.upper()
    if "MEGA" in tier_upper:
        return "Mega Raid"
    if "ULTRA_BEAST" in tier_upper:
        return "Ultra Beast Raid"
    if "ELITE" in tier_upper:
        return "Elite Raid"
    if "SHADOW" in tier_upper:
        level_match = re.search(r"RAID_LEVEL_(\d)", tier_upper)
        if level_match:
            return f"Shadow Tier {level_match.group(1)} Raid"
        return "Shadow Raid"
    if "RAID_LEVEL" in tier_upper:
        level_match = re.search(r"RAID_LEVEL_(\d)", tier_upper)
        if level_match:
            return f"Tier {level_match.group(1)} Raid"
    return tier.replace("_", " ").title() if tier else "Unknown"


def format_timestamp(ms: Optional[int], fallback: Optional[str]) -> Optional[str]:
    if ms:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    return fallback


def build_raid_entries(
    data_blob: Dict,
    display_map: Dict[str, Dict[str, Optional[str]]],
    base_url: str,
) -> List[Dict[str, Optional[str]]]:
    raids: List[Dict[str, Optional[str]]] = []
    raids_store = data_blob.get("raidsStore", {})
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    upcoming_cutoff = now_ms + 3 * 24 * 60 * 60 * 1000
    seen_keys = set()
    for tier_info in raids_store.values():
        for raid in tier_info.get("raids", []):
            slug = raid.get("pokemonId") or raid.get("pokemon")
            if not slug:
                continue

            start_ms = raid.get("startDate")
            end_ms = raid.get("endDate")
            if start_ms is None:
                continue
            if start_ms > upcoming_cutoff:
                continue
            if start_ms <= now_ms:
                if end_ms is not None and end_ms < now_ms:
                    continue

            display = display_map.get(slug, {})
            if not display:
                continue
            dedupe_key = slug
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            entry = {
                "pokemon": display.get("name")
                or raid.get("pokemon")
                or slug.replace("_", " ").title(),
                "image": display.get("image"),
                "start_local": raid.get("localStartDate"),
                "end_local": raid.get("localEndDate"),
                "start_utc": format_timestamp(raid.get("startDate"), None),
                "end_utc": format_timestamp(raid.get("endDate"), None),
                "difficulty": display.get("difficulty") or humanize_tier(raid.get("tier", "")),
                "tier": humanize_tier(raid.get("tier", "")),
                "tier_raw": raid.get("tier"),
                "pokebattler_url": urljoin(base_url, f"/raids/{slug}"),
                "_slug": slug,
            }
            raids.append(entry)
    raids.sort(key=lambda item: (item.get("start_utc") or "", item.get("pokemon") or ""))
    return raids


asset_pattern = re.compile(r'(?:https?:)?//static\.pokebattler\.com/assets/pokemon/[^"\'<>\s]+', re.IGNORECASE)
boss_icon_pattern = re.compile(r'(?:https?:)?//static\.pokebattler\.com/assets/pokemon/256/[^"\'<>\s]+', re.IGNORECASE)


def _extract_icon_url(html: str, display_name: Optional[str]) -> Optional[str]:
    boss_match = boss_icon_pattern.search(html)
    if boss_match:
        url = boss_match.group(0)
        return f"https:{url}" if url.startswith("//") else url
    if display_name:
        escaped = re.escape(display_name)
        svg_pattern = re.compile(
            rf'<svg[^>]+aria-label="{escaped}".*?</svg>', re.IGNORECASE | re.DOTALL
        )
        svg_match = svg_pattern.search(html)
        if svg_match:
            asset_match = asset_pattern.search(svg_match.group(0))
            if asset_match:
                url = asset_match.group(0)
                return f"https:{url}" if url.startswith("//") else url
    return None


def populate_missing_images(
    raids: List[Dict[str, Optional[str]]],
    session: requests.Session,
    base_url: str,
) -> None:
    cache: Dict[str, Optional[str]] = {}
    image_pattern = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.IGNORECASE)
    for raid in raids:
        if raid.get("image"):
            continue
        slug = raid.get("_slug")
        if not slug:
            continue
        if slug in cache:
            raid["image"] = cache[slug]
            continue
        detail_url = urljoin(base_url, f"/raids/{slug}")
        try:
            html = fetch_html(detail_url, session=session)
        except requests.RequestException:
            cache[slug] = None
            continue
        icon_url = _extract_icon_url(html, raid.get("pokemon"))
        if icon_url:
            cache[slug] = icon_url
            raid["image"] = icon_url
            continue
        meta_match = image_pattern.search(html)
        if meta_match:
            cache[slug] = meta_match.group(1)
            raid["image"] = meta_match.group(1)
        else:
            cache[slug] = None


def write_output(path: Path, payload: List[Dict[str, Optional[str]]]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=POKEBATTLER_RAIDS_URL, help="Source page to scrape")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write the JSON payload")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    with create_session() as session:
        html = fetch_html(args.url, session=session)
        data_blob = extract_rehydrate_blob(html)
        display_map = extract_display_metadata(html)
        raids = build_raid_entries(data_blob, display_map, args.url)
        populate_missing_images(raids, session, args.url)
    for raid in raids:
        raid.pop("_slug", None)
    output_path = Path(args.output)
    write_output(output_path, raids)
    print(f"Wrote {len(raids)} raids to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
