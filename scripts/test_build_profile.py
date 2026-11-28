"""build_profile.py testleri (ağ yok): python -m unittest scripts/test_build_profile.py"""

from __future__ import annotations

import datetime as dt
import json
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
        "lastWorkAt": None, "activityScore": 0, "latestRelease": None,
    }
    if kw.get("activityScore") and "lastWorkAt" not in kw:
        kw["lastWorkAt"] = bp.fmt_ts(NOW)  # rank_score = activityScore
    if kw.get("activityScore") and "focus" not in kw:
        kw["focus"] = {"en": "Working", "tr": "Çalışılıyor"}  # focus'suz repo Now'a girmez
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

    def test_repo_without_focus_is_skipped_not_leaked(self):
        focus = {"en": "Doing X", "tr": "X yapılıyor"}
        repos = {"a": entry(activityScore=2, focus=focus),
                 "b": entry(activityScore=3, focus=None, description="Raw English GitHub description")}
        items = bp.build_now(repos, NOW)
        self.assertEqual([i["repo"] for i in items], ["a"])
        self.assertEqual(items[0]["text"], focus)
        self.assertNotIn("Raw English", json.dumps(items, ensure_ascii=False))

    def test_skipped_focusless_repo_does_not_use_up_work_slot(self):
        repos = {f"w{i}": entry(activityScore=5 - i) for i in range(3)}
        repos["nofocus"] = entry(activityScore=9, focus=None)
        repos["w3"] = entry(activityScore=0.4)
        items = bp.build_now(repos, NOW)
        self.assertEqual([i["repo"] for i in items], ["w0", "w1", "w2"])

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
            "blurbs": {"a": "text", "b": "other"},
            "labels": {"b": "Etiket"},
        }
        html = bp.render_featured(cfg)
        self.assertEqual(html.count("<tr>"), 2)
        self.assertEqual(html.count("<td"), 4)  # tek sayıda öğe: son hücre boş
        self.assertIn('<a href="https://github.com/o/r"><img src="img.png" alt="alt" width="100%"></a>', html)
        repos = {"a": entry(url="https://github.com/o/a"), "b": entry(url="https://github.com/o/b")}
        self.assertEqual(bp.render_more(cfg, repos, []),
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
    def __init__(self, repos, statuses=None, commits=None, releases=None, fail=(), pinned=None):
        self._repos, self.statuses = repos, statuses or {}
        self._pinned = pinned
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

    def pinned(self, owner):
        if isinstance(self._pinned, Exception):
            raise self._pinned
        return self._pinned or []


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
        self.assertEqual(repos["a"]["activityScore"], 1)
        self.assertEqual(repos["a"]["lastWorkAt"], "2026-11-24T00:00:00Z")
        self.assertEqual(set(bp.strip_private(repos)["a"]), {"url", "description", "status", "focus", "note", "stars", "archived",
                                           "pushedAt", "lastWorkAt", "activityScore", "latestRelease"})

    def test_archived_skips_commits(self):
        api = FakeApi([gh_repo("old", archived=True), gh_repo("s")], statuses={"s": "status: archived\n"},
                      commits={"old": [commit()], "s": [commit()]})
        repos = bp.collect(api, "o", NOW)
        self.assertEqual((repos["old"]["activityScore"], repos["s"]["activityScore"]), (0, 0))

    def test_invalid_status_is_ignored(self):
        api = FakeApi([gh_repo("a")], statuses={"a": "status: nonsense\n"})
        repos = bp.collect(api, "o", NOW)
        self.assertEqual((repos["a"]["status"], repos["a"]["focus"]), (None, None))

    def test_api_failure_keeps_previous_values(self):
        prev = {"a": entry(activityScore=3.21, lastWorkAt="2026-11-24T00:00:00Z")}
        api = FakeApi([gh_repo("a")], fail={"a"})
        repos = bp.collect(api, "o", NOW, prev)
        self.assertEqual(repos["a"]["activityScore"], 3)
        self.assertEqual(repos["a"]["lastWorkAt"], "2026-11-24T00:00:00Z")


class NoiseReduction(unittest.TestCase):
    def test_bucket_score_is_integer_and_capped(self):
        self.assertEqual([bp.bucket_score(x) for x in (0, 0.4, 0.6, 1.5, 2.49, 7.9)], [0, 0, 1, 2, 2, 3])
        self.assertIsInstance(bp.bucket_score(1.2), int)

    def test_day_precision(self):
        self.assertEqual(bp.day_precision("2026-11-24T17:45:12Z"), "2026-11-24T00:00:00Z")
        self.assertIsNone(bp.day_precision(None))
        self.assertEqual(bp.day_precision("bozuk"), "bozuk")

    def test_collected_entry_stable_across_days(self):
        commits = {"a": [commit(days_ago=2.3), commit(days_ago=3.1)]}
        a = bp.collect(FakeApi([gh_repo("a")], commits=commits), "o", NOW)["a"]
        b = bp.collect(FakeApi([gh_repo("a")], commits=commits), "o", NOW + dt.timedelta(hours=7))["a"]
        self.assertEqual((a["activityScore"], a["lastWorkAt"]), (b["activityScore"], b["lastWorkAt"]))


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
        self.assertEqual(list(__import__("json").loads(out)), ["schemaVersion", "generatedAt", "owner", "now", "repos", "pinned"])
        self.assertIn("ü", bp.dump_profile({"x": "ü"}))


def gql(*nodes):
    return {"data": {"user": {"pinnedItems": {"nodes": list(nodes)}}}}


def node(name, owner="o", private=False):
    return {"name": name, "owner": {"login": owner}, "isPrivate": private}


class Pinned(unittest.TestCase):
    def test_order_kept(self):
        self.assertEqual(bp.parse_pinned(gql(node("b"), node("a"), node("c")), "o"), ["b", "a", "c"])

    def test_private_other_owner_and_non_repo_ignored(self):
        payload = gql(node("pub"), node("secret", private=True), node("theirs", owner="x"), {},
                      {"name": "nolabel"}, node("same", owner="O"))
        self.assertEqual(bp.parse_pinned(payload, "o"), ["pub", "same"])

    def test_unknown_privacy_is_not_listed(self):
        self.assertEqual(bp.parse_pinned(gql({"name": "a", "owner": {"login": "o"}}), "o"), [])

    def test_duplicates_and_cap(self):
        self.assertEqual(bp.parse_pinned(gql(node("a"), node("a")), "o"), ["a"])
        many = gql(*[node(f"r{i}") for i in range(9)])
        self.assertEqual(len(bp.parse_pinned(many, "o")), bp.MAX_PINNED)

    def test_malformed_raises(self):
        for payload in (None, [], {}, {"data": None}, {"data": {"user": None}},
                        {"errors": [{"message": "x"}], "data": None},
                        {"data": {"user": {"pinnedItems": {"nodes": None}}}}):
            with self.assertRaises(bp.ApiError, msg=payload):
                bp.parse_pinned(payload, "o")

    def test_no_token_raises_without_network(self):
        with self.assertRaises(bp.ApiError):
            bp.GitHub(None).pinned("o")

    def test_fetch_ok(self):
        self.assertEqual(bp.fetch_pinned(FakeApi([], pinned=["a"]), "o", ["old"]), ["a"])

    def test_fetch_failure_falls_back_to_previous(self):
        api = FakeApi([], pinned=bp.ApiError("boom"))
        self.assertEqual(bp.fetch_pinned(api, "o", ["x", 3, "y"]), ["x", "y"])

    def test_fetch_failure_without_previous_is_empty(self):
        for prev in (None, [], "junk"):
            self.assertEqual(bp.fetch_pinned(FakeApi([], pinned=bp.ApiError("boom")), "o", prev), [])

    def test_fetch_never_raises_on_unexpected_error(self):
        self.assertEqual(bp.fetch_pinned(FakeApi([], pinned=RuntimeError("weird")), "o", None), [])

    def test_profile_json_gains_pinned_and_keeps_shape(self):
        profile = bp.build_profile("o", "t", [], {"a": entry()}, ["a", "b"])
        self.assertEqual(profile["pinned"], ["a", "b"])
        self.assertTrue({"schemaVersion", "generatedAt", "owner", "now", "repos"} <= set(profile))
        self.assertEqual(bp.build_profile("o", "t", [], {})["pinned"], [])

    def test_pinned_change_refreshes_generated_at(self):
        old = bp.build_profile("o", "2026-11-20T03:17:00Z", [], {}, ["a"])
        new = bp.build_profile("o", "", [], {}, ["a", "b"])
        self.assertEqual(bp.stable_generated_at(new, old, NOW), "2026-11-25T12:00:00Z")


class MoreList(unittest.TestCase):
    CFG = {"owner": "o", "featured": [{"repo": "feat"}], "blurbs": {}, "labels": {}}

    def repos(self, **extra):
        base = {n: entry(url=f"https://github.com/o/{n}", description=f"Tool {n}")
                for n in ("feat", "pin", "plain", "gone", "gone2")}
        base["gone"]["archived"] = True
        base["gone2"]["status"] = "archived"
        base.update(extra)
        return base

    def test_excludes_pinned_featured_archived(self):
        self.assertEqual(bp.select_more(self.CFG, self.repos(), ["pin"]), ["plain"])

    def test_pinned_and_featured_match_case_insensitively(self):
        cfg = dict(self.CFG, featured=[{"repo": "FEAT"}])
        self.assertEqual(bp.select_more(cfg, self.repos(), ["PIN"]), ["plain"])

    def test_every_other_repo_listed_when_nothing_pinned(self):
        self.assertEqual(sorted(bp.select_more(self.CFG, self.repos(), [])), ["pin", "plain"])

    def test_order_last_work_then_pushed_then_name(self):
        repos = {
            "z-old": entry(lastWorkAt="2026-11-20T00:00:00Z", pushedAt="2026-11-01T00:00:00Z"),
            "a-new": entry(lastWorkAt="2026-11-24T00:00:00Z", pushedAt="2026-11-01T00:00:00Z"),
            "b-push": entry(lastWorkAt=None, pushedAt="2026-11-23T00:00:00Z"),
            "c-push": entry(lastWorkAt=None, pushedAt="2026-11-10T00:00:00Z"),
            "d-tie": entry(lastWorkAt=None, pushedAt="2026-11-10T00:00:00Z"),
            "never": entry(lastWorkAt=None, pushedAt=None),
        }
        self.assertEqual(bp.select_more({"featured": []}, repos, []),
                         ["a-new", "z-old", "b-push", "c-push", "d-tie", "never"])

    def render(self, repos, **cfg):
        return bp.render_more(dict(self.CFG, **cfg), repos, [])

    def test_blurb_override_beats_description(self):
        repos = {"a": entry(url="https://x/a", description="GitHub text")}
        self.assertEqual(self.render(repos, blurbs={"a": "hand written"}), "- [a](https://x/a): hand written")

    def test_description_fallback_is_lowercased_in_house_style(self):
        cases = {
            "Switch work modes with one command.": "switch work modes with one command",
            "PipeWire microphone DSP": "PipeWire microphone DSP",
            "CVE scanner": "CVE scanner",
            "Discord vanity URL monitor": "Discord vanity URL monitor",
            "A tiny tool...": "a tiny tool...",
        }
        for desc, want in cases.items():
            repos = {"a": entry(url="https://x/a", description=desc)}
            self.assertEqual(self.render(repos), f"- [a](https://x/a): {want}", desc)

    def test_no_blurb_no_description_is_just_the_link(self):
        self.assertEqual(self.render({"a": entry(url="https://x/a", description="")}), "- [a](https://x/a)")

    def test_label(self):
        repos = {"DomainSniper": entry(url="https://x/d", description="")}
        self.assertEqual(self.render(repos, blurbs={"domainsniper": "monitor"}, labels={"DomainSniper": "DomainGözcü"}),
                         "- [DomainSniper](https://x/d) (DomainGözcü): monitor")

    def test_status_hints(self):
        out = {}
        for status in (None, "active", "released", "prototype", "maintenance", "paused"):
            repos = {"a": entry(url="https://x/a", description="d", status=status)}
            out[status] = self.render(repos)
        self.assertEqual(out[None], "- [a](https://x/a): d")
        self.assertEqual(out["active"], out[None])
        self.assertEqual(out["released"], out[None])
        self.assertEqual(out["prototype"], "- [a](https://x/a): d · prototype")
        self.assertEqual(out["maintenance"], "- [a](https://x/a): d · maintenance")
        self.assertEqual(out["paused"], "- [a](https://x/a): d · on hold")

    def test_hint_on_link_only_line(self):
        repos = {"a": entry(url="https://x/a", description="", status="paused")}
        self.assertEqual(self.render(repos), "- [a](https://x/a) · on hold")

    def test_untrusted_text_is_sanitized(self):
        desc = "x\n# H <!-- MORE:END --> <img src=x> [l](y) *b*"
        repos = {"a": entry(url="https://x/a", description=desc),
                 "b": entry(url="https://x/b", description="")}
        out = self.render(repos, blurbs={"b": "<script>alert(1)</script> [m](n)"})
        self.assertEqual(out.count("\n"), 1)  # iki madde, iki satır
        for bad in ("<!--", "<img", "<script", "[l]", "[m]", "*b*"):
            self.assertNotIn(bad, out)

    def test_empty_list_has_placeholder(self):
        self.assertTrue(bp.render_more(self.CFG, {}, []).startswith("- "))

    def test_readme_gets_more_section(self):
        text = "<!-- FEATURED:START -->\n<!-- FEATURED:END -->\n<!-- MORE:START -->\n<!-- MORE:END -->\n<!-- NOW:START -->\n<!-- NOW:END -->\n"
        cfg = dict(self.CFG, featured=[])
        out = bp.render_readme(text, cfg, [], {"a": entry(url="https://x/a", description="Desc")}, [])
        self.assertIn("<!-- MORE:START -->\n- [a](https://x/a): desc\n<!-- MORE:END -->", out)


class FeaturedMeta(unittest.TestCase):
    ITEM = {"repo": "r", "image": "i.png", "alt": "alt", "blurb": "Blurb.", "stack": "Rust · ratatui"}
    REL = {"tag": "v0.1.0", "publishedAt": "2026-11-12T00:00:00Z",
           "url": "https://github.com/o/r/releases/tag/v0.1.0"}

    def test_stack_only_without_live_data(self):
        self.assertEqual(bp.featured_meta(self.ITEM, None), "Rust · ratatui")
        self.assertEqual(bp.featured_meta(self.ITEM, entry()), "Rust · ratatui")

    def test_release_and_status(self):
        out = bp.featured_meta(self.ITEM, entry(latestRelease=self.REL, status="maintenance"))
        self.assertEqual(out, 'Rust · ratatui — <a href="https://github.com/o/r/releases/tag/v0.1.0">v0.1.0</a> · maintenance')

    def test_released_status_hidden_when_tag_shown(self):
        out = bp.featured_meta(self.ITEM, entry(latestRelease=self.REL, status="released"))
        self.assertNotIn("released", out.replace("/releases/", ""))
        self.assertIn(">v0.1.0</a>", out)

    def test_status_without_release(self):
        self.assertEqual(bp.featured_meta(self.ITEM, entry(status="released")), "Rust · ratatui — released")
        self.assertEqual(bp.featured_meta(self.ITEM, entry(status="paused")), "Rust · ratatui — on hold")

    def test_stars_only_when_positive(self):
        self.assertNotIn("★", bp.featured_meta(self.ITEM, entry(stars=0)))
        self.assertTrue(bp.featured_meta(self.ITEM, entry(stars=12)).endswith("★ 12"))

    def test_untrusted_values_escaped(self):
        rel = {"tag": 'v1"><script>', "url": 'https://github.com/o/r/"><img src=x>'}
        out = bp.featured_meta(self.ITEM, entry(latestRelease=rel))
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertNotIn('"><', out)

    def test_non_github_release_url_not_linked(self):
        rel = {"tag": "v1", "url": "javascript:alert(1)"}
        out = bp.featured_meta(self.ITEM, entry(latestRelease=rel))
        self.assertNotIn("href", out)
        self.assertIn("v1", out)

    def test_stack_is_escaped_and_empty_meta_possible(self):
        self.assertEqual(bp.featured_meta({"stack": "C&C <x>"}, None), "C&amp;C &lt;x&gt;")
        self.assertEqual(bp.featured_meta({}, None), "")


class FeaturedRender(unittest.TestCase):
    def cfg(self, n, **extra):
        item = {"repo": "r", "image": "i.png", "alt": "alt", "blurb": "Blurb.", "stack": "Rust"}
        return {"owner": "o", "featured": [dict(item, repo=f"r{i}", **extra) for i in range(n)]}

    def test_even_count_has_no_empty_cell(self):
        out = bp.render_featured(self.cfg(4))
        self.assertEqual((out.count("<tr>"), out.count("<td"), out.count("<td width=\"50%\"></td>")), (2, 4, 0))

    def test_odd_count_gets_empty_balancing_cell(self):
        for n, rows in ((1, 1), (3, 2), (5, 3)):
            out = bp.render_featured(self.cfg(n))
            self.assertEqual(out.count("<tr>"), rows, n)
            self.assertEqual(out.count("<td"), rows * 2, n)
            self.assertEqual(out.count('<td width="50%"></td>'), 1, n)
            self.assertEqual(out.count('<td width="50%" valign="top">'), n, n)
            self.assertEqual(out.count("</td>"), out.count("<td"))

    def test_cell_has_live_meta_and_keeps_links_and_alt(self):
        repos = {"r0": entry(status="maintenance", stars=3,
                             latestRelease={"tag": "v1.0", "url": "https://github.com/o/r0/releases/tag/v1.0"})}
        out = bp.render_featured(self.cfg(1), repos)
        self.assertIn('<a href="https://github.com/o/r0"><img src="i.png" alt="alt" width="100%"></a>', out)
        self.assertIn("<br><b><a href=\"https://github.com/o/r0\">r0</a></b><br>", out)
        self.assertIn("Blurb.<br>\n      <sub>Rust — ", out)
        self.assertIn(">v1.0</a> · maintenance · ★ 3</sub>", out)

    def test_missing_repo_data_degrades_to_stack(self):
        out = bp.render_featured(self.cfg(2), {})
        self.assertIn("<sub>Rust</sub>", out)

    def test_attributes_and_text_escaped(self):
        cfg = self.cfg(1)
        cfg["featured"][0].update(image='x.png" onerror="y', alt='a"><b>', blurb="<i>hi</i> & co")
        out = bp.render_featured(cfg)
        self.assertNotIn('onerror="y"', out)
        self.assertNotIn("<i>hi</i>", out)
        self.assertIn("&lt;i&gt;hi&lt;/i&gt; &amp; co", out)

    def test_focus_is_opt_in(self):
        repos = {"r0": entry(focus={"en": "Doing <X>", "tr": "t"})}
        self.assertNotIn("Doing", bp.render_featured(self.cfg(1), repos))
        out = bp.render_featured(self.cfg(1, focus=True), repos)
        self.assertIn("<sub><i>Doing &lt;X&gt;</i></sub>", out)

    def test_cell_without_any_meta_has_no_trailing_br(self):
        cfg = self.cfg(1)
        cfg["featured"][0]["stack"] = ""
        out = bp.render_featured(cfg)
        self.assertNotIn("<sub>", out)
        self.assertIn("      Blurb.\n    </td>", out)


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
        self.assertEqual(bp.collect(Boom([gh_repo("a")]), "o", NOW, prev)["a"]["activityScore"], 2)
        self.assertEqual(bp.collect(BadJson([gh_repo("a")]), "o", NOW, prev)["a"]["activityScore"], 2)
