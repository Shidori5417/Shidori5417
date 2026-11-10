#!/usr/bin/env python3
"""Profil görsellerini üretir: başlık, genel bakış ve dil dağılımı (koyu + açık tema).

Token: GH_STATS_TOKEN (private repoları da sayması için) ya da GITHUB_TOKEN.
Private repo adları hiçbir çıktıya ya da log'a yazılmaz; yalnızca toplamlar kullanılır.
"""

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

API = "https://api.github.com"
OUT = Path(__file__).resolve().parents[1] / "assets"
MAX_LANGS = 8
SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

THEMES = {
    "dark": dict(bg="#0d1117", panel="#161b22", border="#30363d", text="#e6edf3",
                 muted="#8b949e", a1="#58a6ff", a2="#bc8cff", ok="#3fb950"),
    "light": dict(bg="#ffffff", panel="#f6f8fa", border="#d0d7de", text="#1f2328",
                  muted="#59636e", a1="#0969da", a2="#8250df", ok="#1a7f37"),
}

# GitHub linguist renkleri
LANG_COLORS = {
    "Rust": "#dea584", "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
    "Java": "#b07219", "Go": "#00ADD8", "Dart": "#00B4AB", "HTML": "#e34c26", "CSS": "#663399",
    "Shell": "#89e051", "C": "#555555", "C++": "#f34b7d", "Kotlin": "#A97BFF", "Lua": "#000080",
    "Dockerfile": "#384d54", "PowerShell": "#012456", "Batchfile": "#C1F12E", "SCSS": "#c6538c",
    "Swift": "#F05138", "PHP": "#4F5D95", "Nix": "#7e7eff", "Makefile": "#427819",
}


# ---------------------------------------------------------------- GitHub API

def request(url: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "shidori-profile-cards",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()), resp.headers.get("link", "")
    except urllib.error.HTTPError as exc:
        # Private repo bilgisi sızmasın diye yalnızca durum kodu yazılır.
        raise SystemExit(f"GitHub API hatası ({exc.code}). Token izinlerini kontrol et.") from None


def owned_repos(owner: str, token: str) -> list[dict]:
    url = f"{API}/user/repos?affiliation=owner&visibility=all&per_page=100"
    repos: list[dict] = []
    while url:
        page, link = request(url, token)
        repos += page
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match.group(1) if match else ""
    return [r for r in repos if r["owner"]["login"].lower() == owner.lower() and not r["fork"]]


def collect(owner: str, token: str) -> dict:
    repos = owned_repos(owner, token)
    langs: dict[str, int] = {}
    for repo in repos:
        if repo["name"].lower() == owner.lower():
            continue  # profil reposunun kendisini sayma
        sizes, _ = request(repo["languages_url"], token)
        for name, size in sizes.items():
            langs[name] = langs.get(name, 0) + size

    query = """query($login: String!) { user(login: $login) {
      createdAt
      contributionsCollection { contributionCalendar { totalContributions } totalCommitContributions }
    } }"""
    data, _ = request(f"{API}/graphql", token, {"query": query, "variables": {"login": owner}})
    user = data["data"]["user"]
    cc = user["contributionsCollection"]

    return {
        "repos": len(repos),
        "public": sum(not r["private"] for r in repos),
        "stars": sum(r["stargazers_count"] for r in repos if not r["private"]),
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "since": user["createdAt"][:4],
        "langs": dict(sorted(langs.items(), key=lambda kv: kv[1], reverse=True)),
    }


# ---------------------------------------------------------------- SVG

def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def frame(w: int, h: int, t: dict, title: str, body: str, extra_css: str = "") -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">
<title>{esc(title)}</title>
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{t['a1']}"/><stop offset="1" stop-color="{t['a2']}"/>
  </linearGradient>
</defs>
<style>
  .s {{ font-family: {SANS}; }} .m {{ font-family: {MONO}; }}
  .fade {{ opacity: 0; animation: fade .6s ease-out forwards; }}
  @keyframes fade {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; opacity: 1 !important; }} }}
  {extra_css}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="{t['bg']}" stroke="{t['border']}"/>
{body}
</svg>
"""


def header(t: dict) -> str:
    lines = [
        ("cmd", "whoami"),
        ("out", "Mehmet Karaca · 17 · Türkiye"),
        ("cmd", "cat stack.txt"),
        ("out", "Rust · Linux · PipeWire · ratatui · Next.js"),
        ("cmd", "ls ~/projeler --one-line"),
        ("out", "micforge  domain-gozcu  vanity-gozcu  portfolio"),
    ]
    tx, ty = 452, 28
    rows = []
    for i, (kind, text) in enumerate(lines):
        y = ty + 60 + i * 24
        delay = 0.4 + i * 0.45
        if kind == "cmd":
            content = (f'<tspan fill="{t["ok"]}">shidori</tspan><tspan fill="{t["muted"]}">@</tspan>'
                       f'<tspan fill="{t["a1"]}">cachyos</tspan><tspan fill="{t["muted"]}"> ~ ❯ </tspan>'
                       f'<tspan fill="{t["text"]}">{esc(text)}</tspan>')
        else:
            content = f'<tspan fill="{t["muted"]}">{esc(text)}</tspan>'
        rows.append(f'<text class="m fade" x="{tx + 20}" y="{y}" font-size="12.5" '
                    f'style="animation-delay:{delay:.2f}s">{content}</text>')
    cursor_y = ty + 60 + len(lines) * 24
    cursor_delay = 0.4 + len(lines) * 0.45
    body = f"""
<g class="s">
  <text class="fade" x="44" y="78" font-size="13" letter-spacing="3" fill="{t['muted']}" style="animation-delay:.05s">MERHABA, BEN</text>
  <text class="fade" x="40" y="138" font-size="62" font-weight="800" fill="url(#g)" style="animation-delay:.15s">Shidori</text>
  <text class="fade" x="44" y="174" font-size="16" fill="{t['text']}" style="animation-delay:.3s">Linux'ta, terminalde yaşayan araçlar yapıyorum.</text>
  <g class="fade" style="animation-delay:.45s">
    <rect x="44" y="198" width="74" height="26" rx="13" fill="none" stroke="{t['border']}"/>
    <text x="81" y="215" font-size="12" text-anchor="middle" fill="{t['text']}">🦀 Rust</text>
    <rect x="126" y="198" width="84" height="26" rx="13" fill="none" stroke="{t['border']}"/>
    <text x="168" y="215" font-size="12" text-anchor="middle" fill="{t['text']}">🐧 Linux</text>
    <rect x="218" y="198" width="116" height="26" rx="13" fill="none" stroke="{t['border']}"/>
    <text x="276" y="215" font-size="12" text-anchor="middle" fill="{t['text']}">⚡ Next.js / TS</text>
  </g>
</g>
<g>
  <rect x="{tx}" y="{ty}" width="420" height="226" rx="10" fill="{t['panel']}" stroke="{t['border']}"/>
  <circle cx="{tx + 18}" cy="{ty + 17}" r="5" fill="#ff5f57"/>
  <circle cx="{tx + 34}" cy="{ty + 17}" r="5" fill="#febc2e"/>
  <circle cx="{tx + 50}" cy="{ty + 17}" r="5" fill="#28c840"/>
  <text class="m" x="{tx + 210}" y="{ty + 21}" font-size="11" text-anchor="middle" fill="{t['muted']}">kitty — fish</text>
  <line x1="{tx}" y1="{ty + 33}" x2="{tx + 420}" y2="{ty + 33}" stroke="{t['border']}"/>
  {''.join(rows)}
  <text class="m fade" x="{tx + 20}" y="{cursor_y}" font-size="12.5" style="animation-delay:{cursor_delay:.2f}s"><tspan fill="{t['ok']}">shidori</tspan><tspan fill="{t['muted']}">@</tspan><tspan fill="{t['a1']}">cachyos</tspan><tspan fill="{t['muted']}"> ~ ❯ </tspan></text>
  <rect class="cursor" x="{tx + 184}" y="{cursor_y - 11}" width="8" height="14" fill="{t['a1']}" style="animation-delay:{cursor_delay:.2f}s"/>
</g>"""
    css = (".cursor { opacity: 0; animation: blink 1s step-end infinite; } "
           "@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }")
    return frame(900, 280, t, "Shidori — Mehmet Karaca", body, css)


def overview(t: dict, s: dict) -> str:
    top = next(iter(s["langs"]), "—")
    stats = [
        ("Toplam repo", s["repos"]), ("Public repo", s["public"]), ("Yıldız", s["stars"]),
        ("Katkı · son 1 yıl", s["contributions"]), ("Commit · son 1 yıl", s["commits"]), ("En çok dil", top),
    ]
    cells = []
    for i, (label, value) in enumerate(stats):
        x = 28 + (i % 3) * 132
        y = 92 + (i // 3) * 78
        cells.append(
            f'<g class="fade" style="animation-delay:{0.1 + i * 0.08:.2f}s">'
            f'<rect x="{x - 10}" y="{y - 34}" width="3" height="48" rx="1.5" fill="url(#g)"/>'
            f'<text class="s" x="{x}" y="{y}" font-size="26" font-weight="700" fill="{t["text"]}">{esc(value)}</text>'
            f'<text class="s" x="{x}" y="{y + 20}" font-size="11" fill="{t["muted"]}">{esc(label)}</text></g>'
        )
    today = dt.date.today().strftime("%d.%m.%Y")
    body = f"""
<text class="s" x="24" y="36" font-size="15" font-weight="700" fill="{t['text']}">Genel bakış</text>
<text class="s" x="416" y="36" font-size="10.5" text-anchor="end" fill="{t['muted']}">{today}</text>
{''.join(cells)}
<text class="s" x="24" y="234" font-size="10" fill="{t['muted']}">Toplam, private repoları da içerir · {esc(s['since'])}'ten beri GitHub'da</text>"""
    return frame(440, 250, t, "GitHub genel bakış", body)


def languages(t: dict, s: dict) -> str:
    items = list(s["langs"].items())
    total = sum(v for _, v in items) or 1
    shown = items[:MAX_LANGS]
    rest = total - sum(v for _, v in shown)
    if rest > 0:
        shown.append(("Diğer", rest))

    bar, x = [], 24.0
    for name, value in shown:
        w = 392 * value / total
        bar.append(f'<rect x="{x:.2f}" y="56" width="{max(w, 0):.2f}" height="10" '
                   f'fill="{LANG_COLORS.get(name, t["muted"])}"/>')
        x += w

    legend = []
    for i, (name, value) in enumerate(shown):
        lx = 24 + (i % 2) * 200
        ly = 100 + (i // 2) * 28
        legend.append(
            f'<g class="fade" style="animation-delay:{0.1 + i * 0.06:.2f}s">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{LANG_COLORS.get(name, t["muted"])}"/>'
            f'<text class="s" x="{lx + 16}" y="{ly}" font-size="12.5" fill="{t["text"]}">{esc(name)}</text>'
            f'<text class="s" x="{lx + 182}" y="{ly}" font-size="12" text-anchor="end" fill="{t["muted"]}">'
            f'{100 * value / total:.1f}%</text></g>'
        )
    body = f"""
<text class="s" x="24" y="36" font-size="15" font-weight="700" fill="{t['text']}">En çok kullandığım diller</text>
<clipPath id="bar"><rect x="24" y="56" width="392" height="10" rx="5"/></clipPath>
<g clip-path="url(#bar)">{''.join(bar)}</g>
{''.join(legend)}"""
    return frame(440, 250, t, "Dil dağılımı", body)


def main() -> int:
    owner = os.environ.get("PROFILE_OWNER", "Shidori5417")
    OUT.mkdir(exist_ok=True)
    for name, t in THEMES.items():
        (OUT / f"header-{name}.svg").write_text(header(t), encoding="utf-8")

    if "--header-only" in sys.argv:
        return 0
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_STATS_TOKEN ya da GITHUB_TOKEN gerekli.")

    stats = collect(owner, token)
    if stats["repos"] == stats["public"]:
        # Token private repoları görmüyor; eksik veriyle kartları bozma.
        print("::warning::Token private repoları göremiyor, kartlar güncellenmedi. "
              "GH_STATS_TOKEN'a tüm repolar için okuma izni ver.")
        return 0
    for name, t in THEMES.items():
        (OUT / f"overview-{name}.svg").write_text(overview(t, stats), encoding="utf-8")
        (OUT / f"languages-{name}.svg").write_text(languages(t, stats), encoding="utf-8")
    print(f"{stats['repos']} repo ({stats['public']} public), {len(stats['langs'])} dil işlendi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
