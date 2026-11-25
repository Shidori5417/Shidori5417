#!/usr/bin/env python3
"""README'nin Featured / More / Now bölümlerini ve data/profile.json dosyasını üretir.

Kaynaklar:
  - data/projects.yml        Featured ve More içeriği (elle yazılır)
  - <repo>/.github/status.yml Her reponun kendi durumu (status, focus, note)
  - GitHub API               Repo listesi, son 14 günün commit'leri, son release

Yalnızca public, fork olmayan repolar işlenir; private repo adları hiçbir çıktıya yazılmaz.
Token: GITHUB_TOKEN (isteğe bağlı, rate limit için). Sahip: PROFILE_OWNER.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PROJECTS = ROOT / "data" / "projects.yml"
PROFILE = ROOT / "data" / "profile.json"

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
DEFAULT_OWNER = "Shidori5417"

SCHEMA_VERSION = 1
WINDOW_DAYS = 14
DECAY_DAYS = 7.0
COMMIT_CAP = 300
MIN_SCORE = 0.3
MAX_WORK = 3
MAX_NOW = 4
RELEASE_DAYS = 14
STATUSES = ("active", "prototype", "released", "maintenance", "paused", "archived")

QUIET_EN = "Quiet stretch; see the repos above."
QUIET_TR = "Sakin bir dönem; yukarıdaki projelere göz atın."

NOISE_PREFIX = re.compile(r"^(docs|ci|chore|style|build|deps)(\([^)]*\))?!?:", re.I)
FIX_PREFIX = re.compile(r"^fix(\([^)]*\))?!?(:|\s)", re.I)


def warn(msg: str) -> None:
    print(f"uyarı: {msg}", file=sys.stderr)


# ------------------------------------------------------------------ zaman

def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def fmt_ts(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_now(now_date: str | None) -> dt.datetime:
    """--now-date verilirse o günün sonu (UTC), yoksa şimdi."""
    if not now_date:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    day = dt.date.fromisoformat(now_date)
    return dt.datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------- GitHub API

class ApiError(Exception):
    """Geçici ya da beklenmeyen API hatası (404 hariç)."""


class GitHub:
    def __init__(self, token: str | None):
        self.token = token

    def _open(self, url: str, accept: str, auth: bool = True) -> tuple[int, bytes]:
        headers = {"Accept": accept, "User-Agent": "profile-readme-builder"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        last: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 409):  # 409: boş repo
                    return 404, b""
                last = exc
                if exc.code < 500:
                    break
            except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                last = exc
            time.sleep(1 + attempt)
        code = getattr(last, "code", "ağ")
        raise ApiError(f"istek başarısız ({code})")

    def json(self, path: str):
        status, body = self._open(API + path, "application/vnd.github+json")
        if status == 404:
            return None
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ApiError(f"geçersiz JSON ({path})") from exc

    def list_repos(self, owner: str) -> list[dict]:
        repos: list[dict] = []
        page = 1
        while True:
            q = urllib.parse.urlencode({"type": "owner", "per_page": 100, "page": page})
            batch = self.json(f"/users/{owner}/repos?{q}")
            if batch is None:
                raise ApiError("kullanıcı bulunamadı")
            repos.extend(batch)
            if len(batch) < 100:
                return repos
            page += 1

    def commits(self, owner: str, repo: str, since: dt.datetime) -> list[dict]:
        out: list[dict] = []
        page = 1
        while len(out) < COMMIT_CAP:
            q = urllib.parse.urlencode({"since": fmt_ts(since), "per_page": 100, "page": page})
            batch = self.json(f"/repos/{owner}/{repo}/commits?{q}")
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out[:COMMIT_CAP]

    def latest_release(self, owner: str, repo: str) -> dict | None:
        return self.json(f"/repos/{owner}/{repo}/releases/latest")

    def status_text(self, owner: str, repo: str) -> str | None:
        url = f"{RAW}/{owner}/{repo}/HEAD/.github/status.yml"
        status, body = self._open(url, "text/plain", auth=False)
        return None if status == 404 else body.decode("utf-8")


# ------------------------------------------------------------------ YAML

def load_yaml(text: str):
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML gerekli: pip install pyyaml") from None
    return yaml.safe_load(text)


def _bilingual(value, field: str, required: bool) -> dict | None:
    if value is None:
        if required:
            raise ValueError(f"{field} eksik")
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} en/tr içeren bir eşleme olmalı")
    out = {}
    for lang in ("en", "tr"):
        text = value.get(lang)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{field}.{lang} boş olmayan metin olmalı")
        out[lang] = " ".join(text.split())
    return out


def parse_status(text: str | None) -> dict:
    """status.yml içeriğini doğrular. Dönüş: {status, focus, note}; geçersizse ValueError."""
    empty = {"status": None, "focus": None, "note": None}
    if text is None:
        return empty
    try:
        data = load_yaml(text)
    except SystemExit:
        raise
    except Exception as exc:  # YAML sözdizimi hatası
        raise ValueError(f"YAML okunamadı ({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise ValueError("kök bir eşleme olmalı")
    status = data.get("status")
    if status is not None and status not in STATUSES:
        raise ValueError(f"geçersiz status: {status!r}")
    return {
        "status": status,
        "focus": _bilingual(data.get("focus"), "focus", required=False),
        "note": _bilingual(data.get("note"), "note", required=False),
    }


# --------------------------------------------------------------- aktivite

def commit_weight(commit: dict) -> float:
    """0 = anlamsız commit, 0.5 = fix, 1.0 = diğer anlamlı commit."""
    if len(commit.get("parents") or []) > 1:
        return 0.0
    author = commit.get("author") or {}
    committer = commit.get("committer") or {}
    for user in (author, committer):
        if str(user.get("login") or "").endswith("[bot]"):
            return 0.0
    if author.get("type") == "Bot" or committer.get("type") == "Bot":
        return 0.0
    message = (commit.get("commit") or {}).get("message") or ""
    first = message.strip().splitlines()[0].strip() if message.strip() else ""
    if first.startswith("Merge "):
        return 0.0
    if NOISE_PREFIX.match(first):
        return 0.0
    low = first.lower()
    if "badge" in low or "readme" in low:
        return 0.0
    if FIX_PREFIX.match(first):
        return 0.5
    return 1.0


def commit_time(commit: dict) -> dt.datetime | None:
    meta = commit.get("commit") or {}
    for who in ("committer", "author"):
        stamp = (meta.get(who) or {}).get("date")
        if stamp:
            return parse_ts(stamp)
    return None


def score_commits(commits: list[dict], now: dt.datetime) -> tuple[float, str | None]:
    """(skor, lastWorkAt). Yalnızca son WINDOW_DAYS gün içindeki anlamlı commit'ler sayılır."""
    cutoff = now - dt.timedelta(days=WINDOW_DAYS)
    score = 0.0
    newest: dt.datetime | None = None
    for commit in commits:
        when = commit_time(commit)
        if when is None or when < cutoff or when > now:
            continue
        weight = commit_weight(commit)
        if weight <= 0:
            continue
        age_days = (now - when).total_seconds() / 86400
        score += weight * math.exp(-age_days / DECAY_DAYS)
        if newest is None or when > newest:
            newest = when
    return score, (fmt_ts(newest) if newest else None)


def sum_commits(commits: list[dict], now: dt.datetime) -> tuple[float, str | None]:
    """(pencere içindeki anlamlı commit ağırlıklarının toplamı, lastWorkAt). Zamanla azalmaz."""
    cutoff = now - dt.timedelta(days=WINDOW_DAYS)
    total = 0.0
    newest: dt.datetime | None = None
    for commit in commits:
        when = commit_time(commit)
        if when is None or when < cutoff or when > now:
            continue
        weight = commit_weight(commit)
        if weight <= 0:
            continue
        total += weight
        if newest is None or when > newest:
            newest = when
    return total, (fmt_ts(newest) if newest else None)


def rank_score(r: dict, now: dt.datetime) -> float:
    """Now sıralaması: commit başına zamanla azalan skor (_rank); yoksa
    ağırlıklı toplam, son çalışmanın yaşına göre azaltılır."""
    if r.get("_rank") is not None:
        return float(r["_rank"])
    if not r.get("lastWorkAt"):
        return 0.0
    try:
        age_days = max(0.0, (now - parse_ts(r["lastWorkAt"])).total_seconds() / 86400)
    except (TypeError, ValueError):
        return 0.0
    return float(r.get("activityScore") or 0) * math.exp(-age_days / DECAY_DAYS)


# ------------------------------------------------------------- temizleme

def clean_text(value: str) -> str:
    """Tek satır, HTML yorumu/işaret içermeyen düz metin (JSON ve README için)."""
    text = str(value).replace("<!--", " ").replace("-->", " ")
    return " ".join(text.split())


def md_inline(value: str) -> str:
    """README listesine güvenle girecek metin: HTML ve link sözdizimi kaçışlı."""
    text = clean_text(value)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for ch in "[]`*_|":
        text = text.replace(ch, "\\" + ch)
    return text


# -------------------------------------------------------------- toplama

def is_listed(repo: dict, owner: str) -> bool:
    """Yalnızca public, fork olmayan ve profil reposu olmayan repolar."""
    if repo.get("private") or repo.get("fork"):
        return False
    if repo.get("visibility", "public") != "public":
        return False
    return str(repo.get("name", "")).lower() != owner.lower()


def collect_repo(api, owner: str, repo: dict, now: dt.datetime, prev: dict | None) -> dict:
    """Tek repo için JSON girdisi. Hata olursa önceki değerler korunur, çalışma durmaz."""
    name = repo["name"]
    prev = prev or {}

    try:
        meta = parse_status(api.status_text(owner, name))
    except ValueError as exc:
        warn(f"{name}: status.yml geçersiz ({exc}); yok sayıldı")
        meta = {"status": None, "focus": None, "note": None}
    except ApiError as exc:
        warn(f"{name}: status.yml alınamadı ({exc}); önceki değer korundu")
        meta = {k: prev.get(k) for k in ("status", "focus", "note")}

    archived = bool(repo.get("archived"))
    skip_activity = archived or meta["status"] == "archived"
    weight_sum, last_work, rank = 0.0, None, None
    if not skip_activity:
        try:
            commits = api.commits(owner, name, now - dt.timedelta(days=WINDOW_DAYS))
            weight_sum, last_work = sum_commits(commits, now)
            rank, _ = score_commits(commits, now)
        except ApiError as exc:
            warn(f"{name}: commit'ler alınamadı ({exc}); önceki değer korundu")
            weight_sum, last_work = prev.get("activityScore", 0.0), prev.get("lastWorkAt")

    release = prev.get("latestRelease")
    try:
        raw = api.latest_release(owner, name)
        release = None
        if raw and not raw.get("draft") and not raw.get("prerelease") and raw.get("published_at"):
            parse_ts(raw["published_at"])  # bozuk tarih → aşağıda yakalanır
            release = {"tag": clean_text(raw.get("tag_name") or ""), "publishedAt": raw["published_at"],
                       "url": raw.get("html_url") or f"{repo['html_url']}/releases"}
            if not release["tag"]:
                release = None
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        warn(f"{name}: release alınamadı ({exc}); önceki değer korundu")
        release = prev.get("latestRelease")

    return {
        "url": repo["html_url"],
        "description": clean_text(repo.get("description") or ""),
        "status": meta["status"],
        "focus": meta["focus"],
        "note": meta["note"],
        "stars": int(repo.get("stargazers_count") or 0),
        "archived": archived,
        "pushedAt": repo.get("pushed_at"),
        "lastWorkAt": last_work,
        # Kayıtta zamanla azalan skor değil, penceredeki ağırlıklı commit toplamı
        # tutulur; aksi halde dosya her gün değişir, her gün commit/deploy olur.
        "activityScore": round(weight_sum, 1),
        "latestRelease": release,
        # Yalnızca bu çalışmadaki sıralama için; JSON'a yazılmaz (strip_private).
        "_rank": rank,
    }


def collect(api, owner: str, now: dt.datetime, prev_repos: dict | None = None) -> dict:
    prev_repos = prev_repos or {}
    entries = {}
    for repo in sorted(api.list_repos(owner), key=lambda r: r["name"].lower()):
        if not is_listed(repo, owner):
            continue
        name = repo["name"]
        try:
            entries[name] = collect_repo(api, owner, repo, now, prev_repos.get(name))
        except Exception as exc:  # tek repo yüzünden tüm çalışma düşmesin
            warn(f"{name}: beklenmeyen hata ({exc!r}); önceki değer korundu")
            if prev_repos.get(name):
                entries[name] = prev_repos[name]
    return entries


# ------------------------------------------------------------------ Now

def build_now(repos: dict, now: dt.datetime) -> list[dict]:
    items: list[dict] = []
    ranked = sorted(
        ((name, r) for name, r in repos.items()
         if not r["archived"] and r["status"] != "archived" and rank_score(r, now) > MIN_SCORE),
        key=lambda kv: (-rank_score(kv[1], now), kv[1]["lastWorkAt"] or "", kv[0].lower()),
    )
    for name, r in ranked[:MAX_WORK]:
        fallback = r["description"] or "Recent work"
        fallback_tr = r["description"] or "Son çalışmalar"
        text = r["focus"] or {"en": fallback, "tr": fallback_tr}
        items.append({"repo": name, "url": r["url"], "kind": "work",
                      "text": {"en": text["en"], "tr": text["tr"]}})
    covered = {i["repo"] for i in items}

    cutoff = now - dt.timedelta(days=RELEASE_DAYS)
    releases = []
    for name, r in repos.items():
        rel = r["latestRelease"]
        if not rel or name in covered or r["archived"] or r["status"] == "archived":
            continue
        try:
            published = parse_ts(rel["publishedAt"])
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff <= published <= now:
            releases.append((published, name, r, rel))
    for published, name, r, rel in sorted(releases, key=lambda x: (-x[0].timestamp(), x[1].lower())):
        if len(items) >= MAX_NOW:
            break
        items.append({
            "repo": name, "url": r["url"], "kind": "release", "tag": rel["tag"],
            "date": published.date().isoformat(),
            "text": {"en": f"{name} {rel['tag']} is out", "tr": f"{name} {rel['tag']} yayınlandı"},
        })
    return items[:MAX_NOW]


# ----------------------------------------------------------- README render

def render_featured(cfg: dict) -> str:
    owner = cfg["owner"]
    cells = []
    for item in cfg["featured"]:
        url = f"https://github.com/{owner}/{item['repo']}"
        cells.append(
            '    <td width="50%" valign="top">\n'
            f'      <a href="{url}"><img src="{html.escape(item["image"])}" alt="{html.escape(item["alt"])}" width="100%"></a>\n'
            f'      <br><b><a href="{url}">{item["repo"]}</a></b><br>\n'
            f'      {item["blurb"]}<br>\n'
            f'      <sub>{item["stack"]}</sub>\n'
            "    </td>"
        )
    rows = []
    for i in range(0, len(cells), 2):
        rows.append("  <tr>\n" + "\n".join(cells[i:i + 2]) + "\n  </tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def render_more(cfg: dict) -> str:
    owner = cfg["owner"]
    lines = []
    for item in cfg["more"]:
        label = f" ({item['label']})" if item.get("label") else ""
        lines.append(f"- [{item['repo']}](https://github.com/{owner}/{item['repo']}){label}: {item['blurb']}")
    return "\n".join(lines)


def render_now(items: list[dict]) -> str:
    if not items:
        return f"- {QUIET_EN}"
    lines = []
    for item in items:
        link = f"[{md_inline(item['repo'])}]({item['url']})"
        if item["kind"] == "release":
            lines.append(f"- {link} {md_inline(item['tag'])} is out")
        else:
            lines.append(f"- {link}: {md_inline(item['text']['en'])}")
    return "\n".join(lines)


def replace_between_markers(text: str, name: str, body: str) -> str:
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    if i < 0 or j < 0 or j < i:
        raise ValueError(f"README'de {start} / {end} işaretleri bulunamadı")
    return text[:i + len(start)] + "\n" + body + "\n" + text[j:]


def render_readme(text: str, cfg: dict, now_items: list[dict]) -> str:
    text = replace_between_markers(text, "FEATURED", render_featured(cfg))
    text = replace_between_markers(text, "MORE", render_more(cfg))
    return replace_between_markers(text, "NOW", render_now(now_items))


# ------------------------------------------------------------------ JSON

def strip_private(repos: dict) -> dict:
    return {name: {k: v for k, v in r.items() if not k.startswith("_")} for name, r in repos.items()}


def build_profile(owner: str, generated_at: str, now_items: list[dict], repos: dict) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "owner": owner,
        "now": now_items,
        "repos": strip_private(repos),
    }


def dump_profile(profile: dict) -> str:
    return json.dumps(profile, indent=2, ensure_ascii=False) + "\n"


def stable_generated_at(new: dict, old: dict | None, now: dt.datetime) -> str:
    """generatedAt yalnızca başka bir şey değiştiyse yenilenir."""
    if old and old.get("generatedAt"):
        a = {k: v for k, v in new.items() if k != "generatedAt"}
        b = {k: v for k, v in old.items() if k != "generatedAt"}
        if a == b:
            return old["generatedAt"]
    return fmt_ts(now)


def load_previous(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="dosya yazmadan çıktıyı göster")
    ap.add_argument("--now-date", help="test için 'şimdi' yerine ISO tarih (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    owner = os.environ.get("PROFILE_OWNER") or DEFAULT_OWNER
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    now = resolve_now(args.now_date)

    cfg = load_yaml(PROJECTS.read_text(encoding="utf-8"))
    old = load_previous(PROFILE)
    prev_repos = (old or {}).get("repos") or {}

    try:
        repos = collect(GitHub(token), owner, now, prev_repos)
    except ApiError as exc:
        # Hata durumunda mevcut dosyalar bozulmasın.
        print(f"hata: repo listesi alınamadı ({exc}); dosyalar değişmedi", file=sys.stderr)
        return 1

    now_items = build_now(repos, now)
    profile = build_profile(owner, "", now_items, repos)
    profile["generatedAt"] = stable_generated_at(profile, old, now)

    readme_old = README.read_text(encoding="utf-8")
    readme_new = render_readme(readme_old, cfg, now_items)
    payload = dump_profile(profile)

    if args.dry_run:
        print("=== FEATURED ===\n" + render_featured(cfg))
        print("\n=== MORE ===\n" + render_more(cfg))
        print("\n=== NOW ===\n" + render_now(now_items))
        print("\n=== data/profile.json ===\n" + payload, end="")
        return 0

    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    if readme_new != readme_old:
        README.write_text(readme_new, encoding="utf-8")
    PROFILE.write_text(payload, encoding="utf-8")
    print(f"{len(repos)} repo, {len(now_items)} Now maddesi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
