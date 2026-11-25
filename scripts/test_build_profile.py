"""build_profile.py testleri (ağ yok): python -m unittest scripts/test_build_profile.py"""

from __future__ import annotations

import datetime as dt
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_profile as bp  # noqa: E402

NOW = dt.datetime(2026, 11, 25, 12, 0, 0, tzinfo=dt.timezone.utc)


def commit(msg="Add feature", days_ago=0.0, parents=1, author="dev", ctype="User", committer=None):
    when = bp.fmt_ts(NOW - dt.timedelta(days=days_ago))
    return {
        "parents": [{"sha": "x"}] * parents,
        "author": {"login": author, "type": ctype},
        "committer": {"login": committer or author},
        "commit": {"message": msg, "committer": {"date": when}, "author": {"date": when}},
    }


def entry(**kw):
    base = {
        "url": "https://github.com/o/r", "description": "desc", "status": None, "focus": None,
        "note": None, "stars": 0, "archived": False, "pushedAt": "2026-11-25T00:00:00Z",
        "lastWorkAt": None, "activityScore": 0.0, "latestRelease": None,
    }
    if kw.get("activityScore") and "lastWorkAt" not in kw:
        kw["lastWorkAt"] = bp.fmt_ts(NOW)  # rank_score = activityScore
    base.update(kw)
    return base


class CommitWeight(unittest.TestCase):
    def test_regular_commit(self):
        self.assertEqual(bp.commit_weight(commit("Add hot reload")), 1.0)

    def test_fix_is_half(self):
        self.assertEqual(bp.commit_weight(commit("fix: crash on start")), 0.5)
        self.assertEqual(bp.commit_weight(commit("Fix(tui)!: layout")), 0.5)
        self.assertEqual(bp.commit_weight(commit("Fix Linux build")), 0.5)

    def test_feat_and_refactor_full(self):
        self.assertEqual(bp.commit_weight(commit("feat(ui): panel")), 1.0)
        self.assertEqual(bp.commit_weight(commit("refactor: split module")), 1.0)

    def test_noise_prefixes(self):
        for msg in ("docs: update", "CI: pin action", "chore(deps): bump", "style: fmt",
                    "build!: new flags", "deps: bump serde", "Docs(readme): typo"):
            self.assertEqual(bp.commit_weight(commit(msg)), 0.0, msg)

    def test_merge_variants(self):
        self.assertEqual(bp.commit_weight(commit("Merge branch 'x'")), 0.0)
        self.assertEqual(bp.commit_weight(commit("Add thing", parents=2)), 0.0)

    def test_bots(self):
        self.assertEqual(bp.commit_weight(commit(author="dependabot[bot]")), 0.0)
        self.assertEqual(bp.commit_weight(commit(committer="github-actions[bot]")), 0.0)
        self.assertEqual(bp.commit_weight(commit(ctype="Bot")), 0.0)

    def test_badge_and_readme(self):
        self.assertEqual(bp.commit_weight(commit("Add CI badge")), 0.0)
        self.assertEqual(bp.commit_weight(commit("README tweaks")), 0.0)

    def test_only_first_line_counts(self):
        self.assertEqual(bp.commit_weight(commit("Add parser\n\ndocs: also badge")), 1.0)

    def test_missing_author_is_fine(self):
        c = commit()
        c["author"] = None
        c["committer"] = None
        self.assertEqual(bp.commit_weight(c), 1.0)


class Scoring(unittest.TestCase):
    def test_decay(self):
        score, last = bp.score_commits([commit(days_ago=7)], NOW)
        self.assertAlmostEqual(score, math.exp(-1), places=6)
        self.assertEqual(last, "2026-11-18T12:00:00Z")

    def test_sum_and_weights(self):
        score, _ = bp.score_commits([commit(days_ago=0), commit("fix: x", days_ago=0)], NOW)
        self.assertAlmostEqual(score, 1.5)

    def test_window_and_noise_excluded(self):
        score, last = bp.score_commits(
            [commit(days_ago=15), commit("docs: x", days_ago=0), commit(parents=2)], NOW)
        self.assertEqual((score, last), (0.0, None))

    def test_last_work_is_newest_meaningful(self):
        _, last = bp.score_commits(
            [commit("docs: x", days_ago=0.5), commit(days_ago=3), commit(days_ago=1)], NOW)
        self.assertEqual(last, "2026-11-24T12:00:00Z")


class NowList(unittest.TestCase):
    def test_top_three_work_by_score(self):
        repos = {n: entry(activityScore=s, description=n) for n, s in
                 (("a", 1.0), ("b", 5.0), ("c", 3.0), ("d", 2.0), ("e", 0.3))}
        items = bp.build_now(repos, NOW)
        self.assertEqual([i["repo"] for i in items], ["b", "c", "d"])
        self.assertTrue(all(i["kind"] == "work" for i in items))

    def test_focus_then_description_fallback(self):
        focus = {"en": "Doing X", "tr": "X yapılıyor"}
        repos = {"a": entry(activityScore=2, focus=focus), "b": entry(activityScore=1, description="Desc B")}
        items = bp.build_now(repos, NOW)
        self.assertEqual(items[0]["text"], focus)
        self.assertEqual(items[1]["text"], {"en": "Desc B", "tr": "Desc B"})

    def test_archived_skipped(self):
        repos = {"a": entry(activityScore=9, archived=True), "b": entry(activityScore=9, status="archived")}
        self.assertEqual(bp.build_now(repos, NOW), [])

    def test_release_added_and_formatted(self):
        rel = {"tag": "v0.3.0", "publishedAt": "2026-11-20T08:00:00Z", "url": "u"}
        repos = {"proxyforge": entry(latestRelease=rel, url="https://github.com/o/proxyforge")}
        (item,) = bp.build_now(repos, NOW)
        self.assertEqual(item, {
            "repo": "proxyforge", "url": "https://github.com/o/proxyforge", "kind": "release",
            "tag": "v0.3.0", "date": "2026-11-20",
            "text": {"en": "proxyforge v0.3.0 is out", "tr": "proxyforge v0.3.0 yayınlandı"},
        })

    def test_release_dedupe_with_work_item(self):
        rel = {"tag": "v1", "publishedAt": "2026-11-24T08:00:00Z", "url": "u"}
        repos = {"a": entry(activityScore=2, latestRelease=rel)}
        items = bp.build_now(repos, NOW)
        self.assertEqual([i["kind"] for i in items], ["work"])

    def test_old_release_ignored(self):
        rel = {"tag": "v1", "publishedAt": "2026-10-01T08:00:00Z", "url": "u"}
        self.assertEqual(bp.build_now({"a": entry(latestRelease=rel)}, NOW), [])

    def test_max_four_total(self):
        repos = {f"w{i}": entry(activityScore=5 - i) for i in range(4)}
        for i in range(3):
            repos[f"r{i}"] = entry(latestRelease={"tag": "v1", "publishedAt": f"2026-11-2{i}T00:00:00Z", "url": "u"})
        items = bp.build_now(repos, NOW)
        self.assertEqual(len(items), 4)
        self.assertEqual([i["kind"] for i in items], ["work", "work", "work", "release"])
        self.assertEqual(items[3]["repo"], "r2")  # en yeni release

    def test_empty_fallback_render(self):
        self.assertEqual(bp.render_now([]), "- " + bp.QUIET_EN)

    def test_render_now_lines(self):
        items = [
            {"repo": "a", "url": "https://x/a", "kind": "work", "text": {"en": "Doing X", "tr": "t"}},
            {"repo": "b", "url": "https://x/b", "kind": "release", "tag": "v1", "date": "d",
             "text": {"en": "b v1 is out", "tr": "t"}},
        ]
        self.assertEqual(bp.render_now(items), "- [a](https://x/a): Doing X\n- [b](https://x/b) v1 is out")


class Markers(unittest.TestCase):
    TEXT = "## A\n\n<!-- X:START -->\nold\nmore\n<!-- X:END -->\n\n## B\n"

    def test_replace(self):
        out = bp.replace_between_markers(self.TEXT, "X", "new")
        self.assertEqual(out, "## A\n\n<!-- X:START -->\nnew\n<!-- X:END -->\n\n## B\n")

    def test_idempotent(self):
        once = bp.replace_between_markers(self.TEXT, "X", "new")
        self.assertEqual(bp.replace_between_markers(once, "X", "new"), once)

    def test_missing_markers(self):
        with self.assertRaises(ValueError):
            bp.replace_between_markers("## A\n", "X", "new")

    def test_render_featured_and_more(self):
        cfg = {
            "owner": "o",
            "featured": [{"repo": "r", "image": "img.png", "alt": "alt", "blurb": "Blurb.", "stack": "Rust"}] * 3,
            "more": [{"repo": "a", "blurb": "text"}, {"repo": "b", "label": "Etiket", "blurb": "other"}],
        }
        html = bp.render_featured(cfg)
        self.assertEqual(html.count("<tr>"), 2)
        self.assertEqual(html.count("<td"), 3)
        self.assertIn('<a href="https://github.com/o/r"><img src="img.png" alt="alt" width="100%"></a>', html)
        self.assertEqual(bp.render_more(cfg),
                         "- [a](https://github.com/o/a): text\n- [b](https://github.com/o/b) (Etiket): other")


class StatusYaml(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(bp.parse_status(None), {"status": None, "focus": None, "note": None})

    def test_valid(self):
        s = bp.parse_status('status: active\nfocus:\n  en: "A: b"\n  tr: "B"\nnote:\n  en: n\n  tr: m\n')
        self.assertEqual(s["status"], "active")
        self.assertEqual(s["focus"], {"en": "A: b", "tr": "B"})
        self.assertEqual(s["note"], {"en": "n", "tr": "m"})

    def test_note_optional(self):
        self.assertIsNone(bp.parse_status("status: paused\nfocus: {en: a, tr: b}\n")["note"])

    def test_invalid(self):
        for text in ("status: sleeping\n", "- a\n- b\n", "status: [\n", "focus: {en: a}\n", "focus: text\n"):
            with self.assertRaises(ValueError, msg=text):
                bp.parse_status(text)


class FakeApi:
    def __init__(self, repos, statuses=None, commits=None, releases=None, fail=()):
        self._repos, self.statuses = repos, statuses or {}
        self._commits, self._releases, self.fail = commits or {}, releases or {}, set(fail)
        self.touched: list[str] = []

    def list_repos(self, owner):
        return self._repos

    def status_text(self, owner, repo):
        self.touched.append(repo)
        return self.statuses.get(repo)

    def commits(self, owner, repo, since):
        self.touched.append(repo)
        if repo in self.fail:
            raise bp.ApiError("boom")
        return self._commits.get(repo, [])

    def latest_release(self, owner, repo):
        return self._releases.get(repo)


def gh_repo(name, **kw):
    base = {"name": name, "private": False, "fork": False, "visibility": "public", "archived": False,
            "html_url": f"https://github.com/o/{name}", "description": f"{name} desc",
            "stargazers_count": 2, "pushed_at": "2026-11-24T00:00:00Z"}
    base.update(kw)
    return base


class Collect(unittest.TestCase):
    def test_private_forks_and_profile_repo_excluded(self):
        api = FakeApi([
            gh_repo("pub"), gh_repo("secret", private=True), gh_repo("vis", visibility="private"),
            gh_repo("forked", fork=True), gh_repo("o"),
        ])
        repos = bp.collect(api, "o", NOW)
        self.assertEqual(list(repos), ["pub"])
        # Private repolara hiç istek atılmaz.
        self.assertEqual(set(api.touched), {"pub"})
        self.assertNotIn("secret", bp.dump_profile(bp.build_profile("o", "t", [], repos)))

    def test_entry_shape_and_release_filter(self):
        api = FakeApi(
            [gh_repo("a"), gh_repo("b"), gh_repo("c")],
            commits={"a": [commit(days_ago=1)]},
            releases={
                "a": {"tag_name": "v1", "published_at": "2026-11-20T00:00:00Z", "html_url": "u", "draft": False, "prerelease": False},
                "b": {"tag_name": "v2", "published_at": "2026-11-20T00:00:00Z", "html_url": "u", "draft": False, "prerelease": True},
                "c": {"tag_name": "v3", "published_at": "2026-11-20T00:00:00Z", "html_url": "u", "draft": True, "prerelease": False},
            })
        repos = bp.collect(api, "o", NOW)
        self.assertEqual(repos["a"]["latestRelease"], {"tag": "v1", "publishedAt": "2026-11-20T00:00:00Z", "url": "u"})
        self.assertIsNone(repos["b"]["latestRelease"])
        self.assertIsNone(repos["c"]["latestRelease"])
        self.assertEqual(repos["a"]["activityScore"], 1.0)
        self.assertEqual(set(bp.strip_private(repos)["a"]), {"url", "description", "status", "focus", "note", "stars", "archived",
                                           "pushedAt", "lastWorkAt", "activityScore", "latestRelease"})

    def test_archived_skips_commits(self):
        api = FakeApi([gh_repo("old", archived=True), gh_repo("s")], statuses={"s": "status: archived\n"},
                      commits={"old": [commit()], "s": [commit()]})
        repos = bp.collect(api, "o", NOW)
        self.assertEqual((repos["old"]["activityScore"], repos["s"]["activityScore"]), (0.0, 0.0))

    def test_invalid_status_is_ignored(self):
        api = FakeApi([gh_repo("a")], statuses={"a": "status: nonsense\n"})
        repos = bp.collect(api, "o", NOW)
        self.assertEqual((repos["a"]["status"], repos["a"]["focus"]), (None, None))

    def test_api_failure_keeps_previous_values(self):
        prev = {"a": entry(activityScore=3.21, lastWorkAt="2026-11-24T00:00:00Z")}
        api = FakeApi([gh_repo("a")], fail={"a"})
        repos = bp.collect(api, "o", NOW, prev)
        self.assertEqual(repos["a"]["activityScore"], 3.2)
        self.assertEqual(repos["a"]["lastWorkAt"], "2026-11-24T00:00:00Z")


class GeneratedAt(unittest.TestCase):
    def profile(self, gen, score=1.0):
        return bp.build_profile("o", gen, [], {"a": entry(activityScore=score)})

    def test_kept_when_unchanged(self):
        old = self.profile("2026-11-20T03:17:00Z")
        new = self.profile("")
        self.assertEqual(bp.stable_generated_at(new, old, NOW), "2026-11-20T03:17:00Z")

    def test_refreshed_when_changed(self):
        old = self.profile("2026-11-20T03:17:00Z")
        new = self.profile("", score=2.0)
        self.assertEqual(bp.stable_generated_at(new, old, NOW), "2026-11-25T12:00:00Z")

    def test_no_previous(self):
        self.assertEqual(bp.stable_generated_at(self.profile(""), None, NOW), "2026-11-25T12:00:00Z")

    def test_dump_format(self):
        out = bp.dump_profile(bp.build_profile("o", "t", [], {}))
        self.assertTrue(out.endswith("}\n"))
        self.assertEqual(list(__import__("json").loads(out)), ["schemaVersion", "generatedAt", "owner", "now", "repos"])
        self.assertIn("ü", bp.dump_profile({"x": "ü"}))


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(unittest.TestCase):
    """Kod incelemesinde bulunan hatalar için regresyon testleri."""

    def test_unspaced_noise_readme_and_bot_committer(self):
        for msg in ("chore:bump", "docs:typo", "Update README.md", "Fix README typo"):
            self.assertEqual(bp.commit_weight(commit(msg)), 0.0, msg)
        c = commit()
        c["committer"]["type"] = "Bot"
        self.assertEqual(bp.commit_weight(c), 0.0)

    def test_stored_score_does_not_decay_daily(self):
        commits = [commit(days_ago=1), commit("fix: x", days_ago=2)]
        a, _ = bp.sum_commits(commits, NOW)
        b, _ = bp.sum_commits(commits, NOW + dt.timedelta(days=1))
        self.assertEqual((a, b), (1.5, 1.5))

    def test_ranking_prefers_recent_work(self):
        repos = {"old": entry(activityScore=3, lastWorkAt="2026-11-12T12:00:00Z"),
                 "new": entry(activityScore=2, lastWorkAt="2026-11-25T12:00:00Z")}
        self.assertEqual([i["repo"] for i in bp.build_now(repos, NOW)], ["new", "old"])

    def test_archived_release_skipped(self):
        rel = {"tag": "v1", "publishedAt": "2026-11-24T08:00:00Z", "url": "u"}
        repos = {"a": entry(latestRelease=rel, archived=True), "b": entry(latestRelease=rel, status="archived")}
        self.assertEqual(bp.build_now(repos, NOW), [])

    def test_malformed_release_date_skipped(self):
        rel = {"tag": "v1", "publishedAt": "not-a-date", "url": "u"}
        self.assertEqual(bp.build_now({"a": entry(latestRelease=rel)}, NOW), [])

    def test_now_line_is_sanitized(self):
        items = [{"repo": "a", "url": "https://github.com/o/a", "kind": "work",
                  "text": {"en": "x\n# Heading <!-- NOW:END --> <img src=x> [link](y)", "tr": ""}}]
        out = bp.render_now(items)
        self.assertEqual(out.count("\n"), 0)
        self.assertNotIn("<!-- NOW:END -->", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("[link]", out)

    def test_marker_end_searched_after_start(self):
        text = "<!-- NOW:END -->\n<!-- NOW:START -->\nold\n<!-- NOW:END -->\n"
        self.assertEqual(bp.replace_between_markers(text, "NOW", "new"),
                         "<!-- NOW:END -->\n<!-- NOW:START -->\nnew\n<!-- NOW:END -->\n")

    def test_description_is_single_line(self):
        api = FakeApi([gh_repo("a", description="line1\nline2 <!-- x -->")])
        self.assertEqual(bp.collect(api, "o", NOW)["a"]["description"], "line1 line2 x")

    def test_unexpected_error_keeps_previous_entry(self):
        class Boom(FakeApi):
            def latest_release(self, owner, repo):
                raise RuntimeError("weird")

        class BadJson(FakeApi):
            def commits(self, owner, repo, since):
                raise bp.ApiError("geçersiz JSON")

        prev = {"a": entry(activityScore=2.0)}
        self.assertEqual(bp.collect(Boom([gh_repo("a")]), "o", NOW, prev)["a"]["activityScore"], 2.0)
        self.assertEqual(bp.collect(BadJson([gh_repo("a")]), "o", NOW, prev)["a"]["activityScore"], 2.0)
