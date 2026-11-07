#!/usr/bin/env python3
"""Build a local language breakdown from GitHub's per-repository language byte counts."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

API_ROOT = "https://api.github.com"
ICON_ROOT = "https://cdn.simpleicons.org"
MAX_LANGUAGES = 8
BAR_WIDTH = 500
ROW_HEIGHT = 38

# Simple Icons slugs and official brand colors. Unknown languages get a clean
# local text mark, so the chart never depends on a missing icon.
ICON_MAP: dict[str, tuple[str, str]] = {
    "Python": ("python", "3776AB"),
    "TypeScript": ("typescript", "3178C6"),
    "JavaScript": ("javascript", "F7DF1E"),
    "Java": ("openjdk", "ED8B00"),
    "Rust": ("rust", "DEA584"),
    "Go": ("go", "00ADD8"),
    "Dart": ("dart", "0175C2"),
    "HTML": ("html5", "E34F26"),
    "CSS": ("css", "1572B6"),
    "C": ("c", "A8B9CC"),
    "C++": ("cplusplus", "00599C"),
    "Kotlin": ("kotlin", "7F52FF"),
    "Swift": ("swift", "F05138"),
    "PHP": ("php", "777BB4"),
    "Ruby": ("ruby", "CC342D"),
    "Shell": ("gnubash", "4EAA25"),
    "Lua": ("lua", "2C2D72"),
    "Jupyter Notebook": ("jupyter", "F37626"),
    "Dockerfile": ("docker", "2496ED"),
    "Vue": ("vuedotjs", "4FC08D"),
    "Svelte": ("svelte", "FF3E00"),
    "Elixir": ("elixir", "4B275F"),
    "R": ("r", "276DC3"),
    "Zig": ("zig", "F7A41D"),
    "HCL": ("terraform", "844FBA"),
    "Nix": ("nixos", "5277C3"),
}


def api_get(url: str, token: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Shidori-Language-Stats",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
    except urllib.error.HTTPError as exc:
        # Never expose private repository names or API response details in public logs.
        raise RuntimeError(
            f"GitHub API request failed ({exc.code}). Check GH_STATS_TOKEN permissions."
        ) from exc


def next_page(link_header: str) -> str | None:
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        match = re.search(r"<([^>]+)>", part)
        if match:
            return match.group(1)
    return None


def list_owned_repositories(owner: str, token: str) -> list[dict[str, Any]]:
    url = f"{API_ROOT}/user/repos?affiliation=owner&visibility=all&per_page=100"
    repositories: list[dict[str, Any]] = []

    while url:
        page, headers = api_get(url, token)
        if not isinstance(page, list):
            raise RuntimeError("GitHub returned an unexpected repository-list response.")
        repositories.extend(page)
        url = next_page(headers.get("link", ""))

    # Ignore forks to avoid counting the same upstream code multiple times.
    return [
        repo for repo in repositories
        if repo.get("owner", {}).get("login", "").casefold() == owner.casefold()
        and not repo.get("fork", False)
    ]


def collect_language_bytes(owner: str, token: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    repositories = list_owned_repositories(owner, token)

    if not repositories:
        raise RuntimeError(
            "No owned repositories were returned. Check the token's repository access."
        )

    for repository in repositories:
        languages_url = repository.get("languages_url")
        if not languages_url:
            continue

        language_sizes, _ = api_get(languages_url, token)
        if not isinstance(language_sizes, dict):
            raise RuntimeError("GitHub returned an unexpected language response.")

        for language, byte_count in language_sizes.items():
            if isinstance(byte_count, int) and byte_count > 0:
                totals[language] = totals.get(language, 0) + byte_count

    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))


def format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):,.1f} MB"
    if value >= 1024:
        return f"{value / 1024:,.1f} KB"
    return f"{value:,} B"


def fetch_icon_path(slug: str) -> str | None:
    url = f"{ICON_ROOT}/{quote(slug, safe='')}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "image/svg+xml", "User-Agent": "Shidori-Language-Stats"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            svg = response.read().decode("utf-8")
        paths = re.findall(r'<path\b[^>]*\bd="([^"]+)"', svg)
        if not paths:
            return None
        path = html.unescape(paths[0])
        # Accept only SVG path commands and numeric separators from the icon file.
        if not re.fullmatch(r"[A-Za-z0-9.,\s+\-]+", path):
            return None
        return path
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError):
        return None


def icon_markup(language: str, x: int, y: int) -> str:
    icon = ICON_MAP.get(language)
    if icon:
        slug, color = icon
        path = fetch_icon_path(slug)
        if path:
            safe_path = html.escape(path, quote=True)
            return (
                f'<svg x="{x}" y="{y}" width="21" height="21" viewBox="0 0 24 24" '
                f'aria-label="{html.escape(language, quote=True)} icon">'
                f'<path d="{safe_path}" fill="#{color}"/></svg>'
            )

    mark = html.escape(language[:2].upper(), quote=True)
    return (
        f'<rect x="{x}" y="{y}" width="21" height="21" fill="#161b22" stroke="#30363d"/>'
        f'<text x="{x + 10.5}" y="{y + 14.5}" text-anchor="middle" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="9" '
        f'font-weight="700" fill="#93c5fd">{mark}</text>'
    )


def build_svg(language_bytes: dict[str, int]) -> str:
    top_languages = list(language_bytes.items())[:MAX_LANGUAGES]
    if not top_languages:
        top_languages = []

    height = 166 if not top_languages else 88 + len(top_languages) * ROW_HEIGHT + 36
    generated = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y").upper()

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" '
        f'viewBox="0 0 900 {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Language breakdown by source-code size</title>',
        '<desc id="desc">Programming and markup languages aggregated by GitHub language byte counts across owned repositories. Repository names are not shown.</desc>',
        f'<rect x="0.5" y="0.5" width="899" height="{height - 1}" fill="#0d1117" stroke="#30363d"/>',
        '<text x="28" y="30" fill="#e6edf3" font-family="Arial, Helvetica, sans-serif" font-size="12" font-weight="700" letter-spacing="1.7">LANGUAGE BREAKDOWN</text>',
        f'<text x="872" y="30" text-anchor="end" fill="#8b949e" font-family="Arial, Helvetica, sans-serif" font-size="10" letter-spacing="0.6">CODE BYTES · {generated}</text>',
        '<line x1="28" y1="45" x2="872" y2="45" stroke="#30363d" stroke-width="1"/>',
    ]

    if not top_languages:
        parts.extend([
            '<text x="28" y="91" fill="#c9d1d9" font-family="Arial, Helvetica, sans-serif" font-size="13">No language data found.</text>',
            '<text x="28" y="113" fill="#8b949e" font-family="Arial, Helvetica, sans-serif" font-size="11">Check repository access for the language statistics workflow.</text>',
        ])
    else:
        max_bytes = max(value for _, value in top_languages) or 1
        for index, (language, byte_count) in enumerate(top_languages):
            center_y = 76 + index * ROW_HEIGHT
            safe_name = html.escape(language, quote=True)
            label_size = 11 if len(language) > 16 else 12
            bar_length = max(2, round(BAR_WIDTH * byte_count / max_bytes))
            parts.append(icon_markup(language, 30, center_y - 10))
            parts.append(
                f'<text x="66" y="{center_y + 4}" fill="#c9d1d9" '
                f'font-family="Arial, Helvetica, sans-serif" font-size="{label_size}">{safe_name}</text>'
            )
            parts.append(
                f'<line x1="250" y1="{center_y}" x2="250" y2="{center_y + 0.1}" '
                'stroke="#30363d" stroke-width="1"/>'
            )
            parts.append(
                f'<rect x="250" y="{center_y - 3}" width="{BAR_WIDTH}" height="6" fill="#21262d"/>'
            )
            parts.append(
                f'<rect x="250" y="{center_y - 3}" width="{bar_length}" height="6" fill="#3b82f6"/>'
            )
            parts.append(
                f'<text x="872" y="{center_y + 4}" text-anchor="end" fill="#8b949e" '
                f'font-family="Arial, Helvetica, sans-serif" font-size="11">{format_bytes(byte_count)}</text>'
            )
            if index < len(top_languages) - 1:
                parts.append(
                    f'<line x1="28" y1="{center_y + 18}" x2="872" y2="{center_y + 18}" '
                    'stroke="#21262d" stroke-width="1"/>'
                )

    footer_y = height - 15
    parts.extend([
        f'<line x1="28" y1="{height - 29}" x2="872" y2="{height - 29}" stroke="#21262d" stroke-width="1"/>',
        f'<text x="28" y="{footer_y}" fill="#6e7681" font-family="Arial, Helvetica, sans-serif" font-size="9">GITHUB LANGUAGE API · AGGREGATED CODE BYTES · NO REPOSITORY NAMES EXPOSED</text>',
        '</svg>',
    ])
    return "\n".join(parts) + "\n"


def main() -> int:
    token = os.environ.get("GH_STATS_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not token:
        print("GH_STATS_TOKEN is not configured; no language data was changed.", file=sys.stderr)
        return 2
    if "/" not in repository:
        print("GITHUB_REPOSITORY is missing or invalid.", file=sys.stderr)
        return 2

    owner, _ = repository.split("/", 1)
    language_bytes = collect_language_bytes(owner, token)
    svg = build_svg(language_bytes)

    output_path = Path(__file__).resolve().parents[1] / "top-languages.svg"
    output_path.write_text(svg, encoding="utf-8")
    print(f"Updated {output_path.name} with {len(language_bytes)} languages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
