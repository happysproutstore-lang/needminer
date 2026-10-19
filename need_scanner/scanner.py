"""Orchestration: one term + one or more App Store countries -> a structured result dict.

Steps 1-4 never call an LLM (they work with zero API keys):
  1. Find apps for the term in each country's App Store (rating count = demand).
  2. Fetch their most recent reviews.
  3. Classify each review into complaint categories and extract verbatim wish sentences.
  4. Count complaint / wish phrases in Hacker News comments and Stack Exchange questions.
  5. (optional, --trends) Google Trends yearly growth.
  6. (optional, --llm) group evidence into concrete needs and merge them across sources.

Opportunity score per country = log10(demand) x share of 1-2 star reviews x (1 + wish rate) x 10.
"""

import math
from collections import Counter
from datetime import datetime

from . import appstore, community, llm, trends
from .config import Settings, load_settings
from .text import classify_review, fold, is_willing_to_pay, short_quote, wish_sentences


def analyze_store(term: str, country: str = "us", apps: int = 5, pages: int = 3,
                  settings: Settings = None) -> dict:
    settings = settings or load_settings()
    app_list = appstore.search_apps(term, country, apps, settings)
    categories, wishes, evidence = Counter(), [], []
    total = low = pay = 0
    for app in app_list:
        reviews = appstore.fetch_reviews(app["app_id"], country, pages, settings)
        app["reviews_fetched"] = len(reviews)
        app["low_star_share"] = round(sum(r["stars"] <= 2 for r in reviews) / len(reviews), 2) if reviews else None
        app_categories = Counter()
        for r in reviews:
            total += 1
            low += r["stars"] <= 2
            cats = classify_review(r["title"], r["body"])
            app_categories.update(cats)
            wants_to_pay = is_willing_to_pay(fold(f"{r['title']} {r['body']}"))
            pay += wants_to_pay
            if r["stars"] <= 2 or wants_to_pay or "missing_feature" in cats:
                evidence.append({"source": app["name"], "stars": r["stars"], "pay": wants_to_pay,
                                 "text": f"{r['title']}. {r['body']}".strip(". ")[:400]})
            # A happy 5-star user saying "I wish..." is also an unmet need.
            for s in wish_sentences(r["body"]):
                wishes.append({"app": app["name"], "stars": r["stars"], "quote": short_quote(s),
                               "url": app.get("url") or "", "country": country})
        app["complaint_categories"] = dict(app_categories.most_common())
        categories.update(app_categories)

    demand = sum(a["rating_count"] for a in app_list)
    low_share = low / total if total else 0
    wish_rate = len(wishes) / total if total else 0
    return {
        "country": country, "demand_rating_count": demand, "reviews_analyzed": total,
        "low_star_share": round(low_share, 2), "wish_rate": round(wish_rate, 2), "willing_to_pay": pay,
        "opportunity_score": round(math.log10(demand + 1) * low_share * (1 + wish_rate) * 10, 2),
        "complaint_categories": {c: {"count": n, "share": round(n / total, 2)} for c, n in categories.most_common()}
        if total else {},
        "wishes": wishes, "apps": app_list, "_evidence": evidence,
    }


def scan(term: str, countries=("us",), apps: int = 5, pages: int = 3, community_sources: bool = True,
         se_sites=community.SE_DEFAULT_SITES, hn_count: int = 100, se_count: int = 30,
         use_trends: bool = False, use_llm: bool = None, llm_call=None, settings: Settings = None) -> dict:
    settings = settings or load_settings()
    use_llm = settings.llm_enabled if use_llm is None else use_llm
    result = {"term": term, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
              "countries": list(countries), "method": "rule-based" + (" + LLM grouping" if use_llm else ", no LLM"),
              "stores": [], "community": None, "trends": [], "needs": [], "errors": []}

    for country in countries:
        try:
            result["stores"].append(analyze_store(term, country, apps, pages, settings))
        except Exception as e:  # noqa: BLE001 - one country failing must not stop the others
            result["errors"].append(f"appstore/{country}: {type(e).__name__}: {str(e)[:160]}")

    raw_community = None
    if community_sources:
        raw_community = community.community_evidence(term, hn_count=hn_count, se_sites=se_sites,
                                                     se_count=se_count, settings=settings)
        result["errors"] += raw_community["errors"]
        result["community"] = {
            name: {"scanned": b["scanned"], "matched": b["matched"], "phrase_kinds": b["phrase_kinds"],
                   "willing_to_pay": b["willing_to_pay"], **({"sites": b["sites"]} if "sites" in b else {}),
                   "examples": [{"quote": short_quote(h["text"]), "phrases": h["phrases"], "url": h["url"]}
                                for h in b["evidence"][:5]]}
            for name, b in raw_community["sources"].items()}

    if use_trends:
        result["trends"].append(trends.yearly_growth(term, settings=settings))

    if use_llm:
        try:
            clusters = {}
            for store in result["stores"]:
                c = llm.cluster_needs(term, store["_evidence"], llm_call=llm_call)
                if c:
                    clusters[f"appstore_{store['country']}"] = c
            for name, b in ((raw_community or {}).get("sources") or {}).items():
                c = llm.cluster_needs(term, b["evidence"], llm_call=llm_call)
                if c:
                    clusters[name] = c
            result["needs"] = llm.merge_clusters(term, clusters, result["trends"], llm_call=llm_call)
        except Exception as e:  # noqa: BLE001 - LLM failure never breaks the rule-based report
            result["errors"].append(f"llm: {type(e).__name__}: {str(e)[:160]}")

    for store in result["stores"]:
        store.pop("_evidence", None)
    return result
