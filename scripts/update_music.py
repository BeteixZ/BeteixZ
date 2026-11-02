#!/usr/bin/env python3
"""Build self-contained GitHub profile cards from public ListenBrainz data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


API_ROOT = "https://api.listenbrainz.org/1"
USER_AGENT = "BeteixZ-GitHubProfile/1.0 (https://github.com/BeteixZ/BeteixZ)"
PALETTES = {
    "light": dict(bg="#fafbfc", text="#1a1e26", muted="#636b75", accent="#2f6f5e", warm="#94653c", border="#dce0e6"),
    "dark": dict(bg="#1a1e26", text="#d8dce3", muted="#9aa3ae", accent="#77c6a5", warm="#d0aa7a", border="#363d49"),
}


def clean_text(value: object) -> str:
    """Keep Unicode text, but reject empty metadata and remove XML controls."""
    if not isinstance(value, str):
        raise ValueError("ListenBrainz metadata must be text")
    value = " ".join(value.split())
    value = "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cs"})
    if not value:
        raise ValueError("ListenBrainz returned empty metadata")
    return value


def clip(value: str, max_cells: int) -> str:
    """Bound labels by display width, allowing for Chinese and other wide text."""
    def width(char: str) -> int:
        if unicodedata.combining(char):
            return 0
        return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1

    if sum(width(c) for c in value) <= max_cells:
        return value
    result, used = [], 0
    for char in value:
        cell_width = width(char)
        if used + cell_width > max_cells - 1:
            break
        result.append(char)
        used += cell_width
    return "".join(result).rstrip() + "…"


def utc_timestamp(value: object) -> datetime:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("Invalid ListenBrainz timestamp")
    return datetime.fromtimestamp(value, timezone.utc)


def fetch_json(path: str) -> dict:
    request = urllib.request.Request(
        API_ROOT + path,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                if response.status != 200:
                    raise ValueError(f"ListenBrainz returned HTTP {response.status}; keeping existing cards")
                data = json.load(response)
                if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
                    raise ValueError("Unexpected ListenBrainz response")
                return data["payload"]
        except urllib.error.HTTPError as error:
            if attempt == 2 or error.code not in {429, 500, 502, 503, 504}:
                raise
            delay = error.headers.get("X-RateLimit-Reset-In", "5")
            try:
                delay = max(2, min(30, int(delay)))
            except (TypeError, ValueError):
                delay = 5
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Could not fetch ListenBrainz data")


def load_music(user: str) -> dict:
    encoded_user = urllib.parse.quote(user, safe="")
    recent = fetch_json(f"/user/{encoded_user}/listens?count=3")
    # ListenBrainz asks clients never to exceed one request per second.
    time.sleep(1.1)
    statistics = fetch_json(f"/stats/user/{encoded_user}/artists?range=this_month&count=3")
    raw_listens = recent.get("listens")
    raw_artists = statistics.get("artists")
    if not isinstance(raw_listens, list) or not raw_listens:
        raise ValueError("No recent listens; keeping existing cards")
    if not isinstance(raw_artists, list) or not raw_artists:
        raise ValueError("Artist statistics unavailable; keeping existing cards")

    listens = []
    for raw in raw_listens[:3]:
        metadata = raw["track_metadata"]
        listens.append(dict(
            track=clean_text(metadata["track_name"]),
            artist=clean_text(metadata["artist_name"]),
            time=utc_timestamp(raw["listened_at"]),
        ))
    artists = []
    for raw in raw_artists[:3]:
        count = raw["listen_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Invalid artist listen count")
        artists.append(dict(name=clean_text(raw["artist_name"]), count=count))

    start = utc_timestamp(statistics["from_ts"])
    end = utc_timestamp(statistics["to_ts"])
    if end <= start:
        raise ValueError("Invalid statistics interval")
    # The statistics backend may lag behind the calendar. Use its actual period.
    return dict(user=clean_text(user), listens=listens, artists=artists,
                period=start.strftime("%b %Y").upper(),
                stats_updated=utc_timestamp(statistics["last_updated"]),
                snapshot=datetime.now(timezone.utc))


def text(x: int, y: int, value: str, *, size: int = 14, fill: str = "text",
         weight: int = 400, anchor: str = "start", mono: bool = False,
         clip_path: str | None = None) -> str:
    family = "'Cascadia Code',Consolas,monospace" if mono else "'Segoe UI',Arial,sans-serif"
    clipping = f' clip-path="url(#{clip_path})"' if clip_path else ""
    return (f'<text x="{x}" y="{y}" class="{fill}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" font-family="{family}"{clipping}>'
            f'{html.escape(value, quote=True)}</text>')


def render_card(music: dict, theme: str, *, mobile: bool = False) -> str:
    palette = PALETTES[theme]
    width, height = (420, 366) if mobile else (840, 268)
    description = "; ".join(
        f'{row["track"]} by {row["artist"]}, {row["time"]:%Y-%m-%d %H:%M} UTC'
        for row in music["listens"]
    )
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">Recent listening · {html.escape(music["user"])} on ListenBrainz</title>',
             f'<desc id="desc">{html.escape(description)}</desc>',
             '<style>' + "".join(f'.{name}{{fill:{color}}}' for name, color in palette.items()) + '</style>',
             f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" '
             f'fill="{palette["bg"]}" stroke="{palette["border"]}"/>']
    if mobile:
        parts += ['<defs><clipPath id="mobile-names"><rect x="24" y="48" width="372" height="260"/></clipPath></defs>',
                  text(24, 32, "RECENT SCROBBLES", size=12, fill="accent", weight=600, mono=True),
                  text(396, 32, "LISTENBRAINZ", size=10, fill="muted", anchor="end", mono=True)]
        for index, row in enumerate(music["listens"]):
            y = 78 + index * 88
            parts += [text(24, y, clip(row["track"], 26), size=24, weight=600, clip_path="mobile-names"),
                      text(24, y + 25, clip(row["artist"], 37), size=17, fill="muted", clip_path="mobile-names"),
                      text(24, y + 45, row["time"].strftime("%d %b %Y · %H:%M UTC"),
                           size=12, fill="warm", mono=True)]
        parts += [f'<path d="M24 318H396" stroke="{palette["border"]}"/>',
                  text(24, 342, music["snapshot"].strftime("Snapshot %Y-%m-%d %H:%M UTC"),
                       size=11, fill="muted", mono=True)]
    else:
        parts += ['<defs>'
                  '<clipPath id="recent-track"><rect x="28" y="48" width="466" height="176"/></clipPath>'
                  '<clipPath id="recent-artist"><rect x="28" y="80" width="294" height="144"/></clipPath>'
                  '<clipPath id="top-artist"><rect x="546" y="48" width="266" height="176"/></clipPath>'
                  '</defs>',
                  text(28, 32, "RECENT SCROBBLES", size=11, fill="accent", weight=600, mono=True),
                  text(546, 32, f'TOP ARTISTS · {music["period"]}', size=11, fill="accent", weight=600, mono=True),
                  f'<path d="M520 24V222" stroke="{palette["border"]}"/>']
        for index, row in enumerate(music["listens"]):
            y = 76 + index * 61
            parts += [text(28, y, clip(row["track"], 35 if index == 0 else 45),
                           size=23 if index == 0 else 18, weight=600, clip_path="recent-track"),
                      text(28, y + 22, clip(row["artist"], 31), size=13, fill="muted", clip_path="recent-artist"),
                      text(494, y + 22, row["time"].strftime("%d %b %H:%M UTC"),
                           size=10, fill="warm", anchor="end", mono=True)]
        for index, artist in enumerate(music["artists"]):
            y = 75 + index * 61
            parts += [text(546, y, clip(artist["name"], 27), size=17, weight=600, clip_path="top-artist"),
                      text(546, y + 22, f'{artist["count"]:,} plays', size=12, fill="muted")]
        parts += [f'<path d="M28 226H812" stroke="{palette["border"]}"/>',
                  text(28, 248, music["snapshot"].strftime("Snapshot %Y-%m-%d %H:%M UTC"),
                       size=10, fill="muted", mono=True),
                  text(812, 248, music["stats_updated"].strftime("Stats updated %Y-%m-%d"),
                       size=10, fill="muted", anchor="end", mono=True)]
    parts.append('</svg>\n')
    svg = "\n".join(parts)
    ET.fromstring(svg)
    return svg


def write_cards(music: dict, output_dir: Path) -> list[Path]:
    # Fetch, validate and render everything before replacing any existing output.
    rendered = {}
    for theme in PALETTES:
        for mobile in (False, True):
            name = f'music-{"mobile-" if mobile else ""}{theme}.svg'
            rendered[output_dir / name] = render_card(music, theme, mobile=mobile)
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for destination, svg in rendered.items():
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=output_dir, prefix=".music-", suffix=".tmp", delete=False) as handle:
                handle.write(svg)
                staged.append((Path(handle.name), destination))
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return list(rendered)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="Beteix", help="Public ListenBrainz username")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "assets")
    args = parser.parse_args()
    music = load_music(args.user)
    paths = write_cards(music, args.output_dir)
    print(f'Updated {len(paths)} cards from {len(music["listens"])} real listens; artist period {music["period"]}.')


if __name__ == "__main__":
    main()
