"""Developer-community evidence from official, key-less APIs.

- Hacker News comments via the Algolia HN Search API (https://hn.algolia.com/api).
- Stack Exchange questions via API 2.3 (anonymous quota: 300 requests/day/IP).
  Stack Exchange content is CC BY-SA: reports keep the link to every quoted question.

Complaint / wish phrases are matched and counted by code.
"""

from collections import Counter

import requests

from .config import Settings, http_headers, load_settings
from .text import community_phrases, fold, is_willing_to_pay, matching_excerpt, strip_html

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
SE_SEARCH_URL = "https://api.stackexchange.com/2.3/search/advanced"
SE_DEFAULT_SITES = ("softwareengineering", "webapps", "workplace", "pm")
SE_MIN_QUOTA = 20  # stop querying further sites below this remaining daily quota
SE_BODY_FILTER = "!9_bDDxJY5"  # standard filter that also returns the question body


class HackerNewsClient:
    def __init__(self, settings: Settings = None):
        self.settings = settings or load_settings()

    def comments(self, query: str, count: int = 50) -> list:
        params = {"query": query, "tags": "comment", "hitsPerPage": max(1, min(int(count), 1000))}
        r = requests.get(HN_SEARCH_URL, params=params, headers=http_headers(self.settings),
                         timeout=self.settings.http_timeout)
        r.raise_for_status()
        return [h for h in (r.json().get("hits") or []) if (h.get("comment_text") or "").strip()]


class StackExchangeClient:
    def __init__(self, settings: Settings = None):
        self.settings = settings or load_settings()
        self.quota_remaining = None

    def questions(self, query: str, site: str, count: int = 30) -> list:
        params = {"order": "desc", "sort": "relevance", "q": query, "site": site,
                  "pagesize": max(1, min(int(count), 100)), "filter": SE_BODY_FILTER}
        if self.settings.stackexchange_key:
            params["key"] = self.settings.stackexchange_key
        r = requests.get(SE_SEARCH_URL, params=params, headers=http_headers(self.settings),
                         timeout=self.settings.http_timeout)
        r.raise_for_status()
        data = r.json()
        self.quota_remaining = data.get("quota_remaining")
        return data.get("items", [])


def _empty() -> dict:
    return {"scanned": 0, "matched": 0, "phrase_kinds": Counter(), "willing_to_pay": 0, "evidence": []}


def _add(bucket: dict, label: str, title: str, body: str, url: str) -> None:
    text = f"{title}. {body}".strip(". ")
    bucket["scanned"] += 1
    kinds = community_phrases(text)
    if not kinds:
        return
    pay = is_willing_to_pay(fold(text))
    bucket["matched"] += 1
    bucket["willing_to_pay"] += pay
    bucket["phrase_kinds"].update(kinds.keys())
    bucket["evidence"].append({"source": label, "stars": 1, "pay": pay, "url": url,
                               "phrases": sorted({p for v in kinds.values() for p in v}),
                               "text": (f"{title[:80]}: " if title else "") + matching_excerpt(body)})


def community_evidence(term: str, hn_count: int = 100, se_sites=SE_DEFAULT_SITES, se_count: int = 30,
                       hn_client=None, se_client=None, settings: Settings = None) -> dict:
    """Network: 1 HN request + 1 request per Stack Exchange site. No LLM.

    Returns {"term", "sources": {"hackernews": {...}, "stackexchange": {...}}, "errors": [...]}.
    """
    settings = settings or load_settings()
    errors, sources = [], {}

    if hn_count:
        hn = sources["hackernews"] = _empty()
        try:
            client = hn_client or HackerNewsClient(settings)
            for h in client.comments(term, count=hn_count):
                _add(hn, "Hacker News", h.get("story_title") or "", strip_html(h.get("comment_text") or ""),
                     f"https://news.ycombinator.com/item?id={h.get('objectID')}")
        except Exception as e:  # noqa: BLE001 - one source failing must not stop the others
            errors.append(f"hackernews: {type(e).__name__}: {str(e)[:120]}")

    if se_sites:
        se = sources["stackexchange"] = _empty()
        se["sites"] = {}
        client = se_client or StackExchangeClient(settings)
        for site in se_sites:
            try:
                items = client.questions(term, site=site, count=se_count)
            except Exception as e:  # noqa: BLE001
                errors.append(f"stackexchange/{site}: {type(e).__name__}: {str(e)[:120]}")
                continue
            before = se["matched"]
            for q in items:
                _add(se, f"SE {site}", strip_html(q.get("title") or ""), strip_html(q.get("body") or ""),
                     q.get("link") or "")
            se["sites"][site] = {"scanned": len(items), "matched": se["matched"] - before}
            quota = getattr(client, "quota_remaining", None)
            if quota is not None and quota < SE_MIN_QUOTA:
                errors.append(f"stackexchange: daily quota low ({quota}), remaining sites skipped")
                break

    for bucket in sources.values():
        bucket["phrase_kinds"] = dict(bucket["phrase_kinds"].most_common())
    return {"term": term, "sources": sources, "errors": errors}
