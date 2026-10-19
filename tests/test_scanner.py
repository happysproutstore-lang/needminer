import csv
import json

import pytest

from needminer import appstore, community, llm, report, scanner, trends
from needminer.config import Settings

from .conftest import FakeResponse


def _entry(stars, title, body):
    return {"im:rating": {"label": str(stars)}, "title": {"label": title}, "content": {"label": body},
            "im:version": {"label": "1.0"}, "updated": {"label": "2026-09-26"}}


REVIEWS = [
    _entry(1, "Ripoff", "Subscription is too expensive and they refused a refund."),
    _entry(2, "Broken", "Keeps crashing on launch. I wish it synced with my bank."),
    _entry(5, "Great", "Love it. Please add a yearly budget view! I would pay for a lifetime license."),
    _entry(1, "Ads", "There are ads everywhere."),
]


def fake_store(url, params=None, settings=None):
    if url == appstore.SEARCH_URL:
        return {"results": [{"trackId": 1, "trackName": "Budget X", "artistName": "Dev Co",
                             "userRatingCount": 9999, "averageUserRating": 4.1, "formattedPrice": "Free",
                             "primaryGenreName": "Finance", "trackViewUrl": "https://apps.apple.com/app/id1"}]}
    if "page=1/" in url:
        # first entry is app metadata, not a review
        return {"feed": {"entry": [{"im:name": {"label": "metadata"}}] + REVIEWS}}
    return {"feed": {}}


class FakeHN:
    def comments(self, query, count=50):
        return [{"objectID": "101", "story_title": "Ask HN: budgeting",
                 "comment_text": "<p>I wish there was a tool that did envelopes right.</p>"},
                {"objectID": "102", "story_title": "Show HN", "comment_text": "Nice launch!"}]


class FakeSE:
    quota_remaining = 250

    def questions(self, query, site, count=30):
        return [{"title": "Is there a tool to split shared expenses?", "body": "<p>It is a nightmare.</p>",
                 "link": f"https://{site}.stackexchange.com/q/7"}]


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr(appstore, "_get_json", fake_store)
    monkeypatch.setattr(community, "HackerNewsClient", lambda settings=None: FakeHN())
    monkeypatch.setattr(community, "StackExchangeClient", lambda settings=None: FakeSE())


def test_analyze_store(fake_sources):
    s = scanner.analyze_store("budget", "us", pages=3)
    assert s["reviews_analyzed"] == 4  # metadata entry skipped
    assert s["low_star_share"] == 0.75
    assert s["complaint_categories"]["ads"]["count"] == 1
    assert s["willing_to_pay"] == 1
    assert any(w["stars"] == 5 for w in s["wishes"])  # happy users' wishes count too
    assert all(w["url"] == "https://apps.apple.com/app/id1" for w in s["wishes"])
    assert s["opportunity_score"] > 0


def test_scan_without_llm_is_default(fake_sources):
    r = scanner.scan("budget", countries=["us", "gb"], se_sites=("webapps",))
    assert r["method"] == "rule-based, no LLM" and r["needs"] == []
    assert [s["country"] for s in r["stores"]] == ["us", "gb"]
    assert r["community"]["hackernews"] == {**r["community"]["hackernews"], "scanned": 2, "matched": 1}
    assert r["community"]["stackexchange"]["sites"]["webapps"] == {"scanned": 1, "matched": 1}
    assert all("_evidence" not in s for s in r["stores"])


def test_one_country_failing_does_not_stop_others(fake_sources, monkeypatch):
    original = appstore.search_apps

    def flaky(term, country="us", limit=5, settings=None):
        if country == "xx":
            raise ValueError("boom")
        return original(term, country, limit, settings)
    monkeypatch.setattr(appstore, "search_apps", flaky)
    r = scanner.scan("budget", countries=["xx", "us"], community_sources=False)
    assert len(r["stores"]) == 1 and any("appstore/xx" in e for e in r["errors"])


def test_scan_with_injected_llm(fake_sources):
    def fake_llm(prompt):
        if "CLUSTERS:" in prompt:
            return '{"groups": [{"need": "Bank sync", "clusters": [0, 1, 2, 99]}]}'
        return '{"needs": [{"need": "Bank sync", "type": "feature", "support": [0, 1, 2, 3, 99]}]}'
    r = scanner.scan("budget", countries=["us"], se_sites=("a", "b", "c", "d"), use_llm=True, llm_call=fake_llm)
    assert r["needs"] and r["needs"][0]["need"] == "Bank sync"
    assert not any(e.startswith("llm") for e in r["errors"])


def test_cluster_needs_counts_are_computed_by_code():
    ev = [{"source": "A", "stars": 1, "pay": True, "text": "one-time purchase please"},
          {"source": "B", "stars": 2, "pay": False, "text": "subscription too pricey"},
          {"source": "A", "stars": 1, "pay": False, "text": "ads"},
          {"source": "C", "stars": 1, "pay": False, "text": "so many ads"}]
    fake = lambda p: ('{"needs": [{"need": "One-time purchase", "type": "pricing_model", "support": [0, 1, 99]},'
                      '{"need": "Single text", "type": "other", "support": [2]},'
                      '{"need": "No ads", "type": "ads", "support": [2, 3, 3]}]}')
    out = llm.cluster_needs("budget", ev, llm_call=fake)
    price = next(x for x in out if x["type"] == "pricing_model")
    assert price["evidence_count"] == 2 and price["willing_to_pay"] == 1  # invalid 99 dropped
    assert not any(x["need"] == "Single text" for x in out)
    assert next(x for x in out if x["type"] == "ads")["evidence_count"] == 2  # duplicates counted once
    assert llm.cluster_needs("budget", ev, llm_call=lambda p: "broken") == []


def _cluster(need, apps, n, pay=0):
    return {"need": need, "type": "pricing_model", "evidence_count": n, "willing_to_pay": pay, "apps": apps,
            "quotes": [f"quote {need}"]}


CLUSTERS = {"appstore_us": [_cluster("One-time payment", ["A"], 4, 2), _cluster("Dark mode", ["A"], 3)],
            "appstore_gb": [_cluster("Lifetime licence", ["B"], 5, 1)],
            "hackernews": [_cluster("Pay once", ["Hacker News"], 2)]}
MERGE = lambda p: ('{"groups": [{"need": "Pay once instead of subscription", "clusters": [0, 2, 3, 99]},'
                   '{"need": "Dark mode", "clusters": [1, 2]}]}')


def test_strong_signal_rule():
    out = llm.merge_clusters("budget", CLUSTERS, trend=[{"yearly_change_pct": 20}], llm_call=MERGE)
    first, second = out[0], out[1]
    assert first["strong_signal"] and first["source_count"] == 3 and first["evidence_count"] == 11
    assert first["willing_to_pay"] == 3
    assert second["sources"] == ["appstore_us"] and not second["strong_signal"]  # cluster 2 not reused


def test_declining_trend_blocks_strong_signal():
    out = llm.merge_clusters("budget", CLUSTERS, trend=[{"yearly_change_pct": -40}], llm_call=MERGE)
    assert not any(x["strong_signal"] for x in out)
    out = llm.merge_clusters("budget", CLUSTERS, trend=[{"yearly_change_pct": None}], llm_call=MERGE)
    assert out[0]["strong_signal"]


def test_broken_merge_answer_invents_nothing():
    out = llm.merge_clusters("budget", CLUSTERS, llm_call=lambda p: "broken")
    assert len(out) == 4 and not any(x["strong_signal"] for x in out)


def test_llm_without_key_raises():
    with pytest.raises(RuntimeError):
        llm.gemini_call("x", settings=Settings())


def test_trends_growth_helper():
    g = trends.growth_from_series([10] * 52 + [20] * 52)
    assert g["yearly_change_pct"] == 100.0
    assert trends.growth_from_series([1] * 52 + [2] * 52)["yearly_change_pct"] is None  # too low volume


def test_trends_cooldown_skips_request(tmp_path, monkeypatch):
    state = tmp_path / "t.json"
    monkeypatch.setenv("NEEDMINER_TRENDS_STATE", str(state))
    s = Settings()
    trends._record_429(s, "429 Too Many Requests")
    assert "cooldown" in trends.yearly_growth("budget app", settings=s)["error"]


def test_reports_written(fake_sources, tmp_path):
    r = scanner.scan("budget app", countries=["us"], se_sites=("webapps",))
    md = report.to_markdown(r)
    assert "# Need scan" in md and "Budget X" in md and "What users wish for" in md
    paths = report.write_reports(r, str(tmp_path))
    rows = list(csv.reader(open(paths["apps_csv"], encoding="utf-8")))
    assert rows[0][0] == "country" and rows[1][1] == "Budget X"
    wishes = list(csv.DictReader(open(paths["wishes_csv"], encoding="utf-8")))
    assert wishes and all(w["url"] for w in wishes)
    assert json.load(open(paths["json"], encoding="utf-8"))["term"] == "budget app"


def test_cli_no_save(fake_sources, capsys):
    from needminer.cli import main
    assert main(["budget app", "--country", "us", "--se-sites", "webapps", "--no-save"]) == 0
    assert "Need scan" in capsys.readouterr().out


def test_stackexchange_key_from_env(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params=params, headers=headers)
        return FakeResponse({"items": [], "quota_remaining": 9000})
    monkeypatch.setenv("STACKEXCHANGE_KEY", "placeholder-key")
    monkeypatch.setattr(community.requests, "get", fake_get)
    c = community.StackExchangeClient(Settings())
    c.questions("x", site="webapps", count=500)
    assert seen["params"]["key"] == "placeholder-key" and seen["params"]["pagesize"] == 100
    assert "needminer" in seen["headers"]["User-Agent"]
