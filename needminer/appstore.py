"""Apple App Store data via public, key-less endpoints.

- iTunes Search API: app name, developer, total rating count (= demand), average rating.
- Customer reviews RSS feed: most recent reviews, 50 per page, up to 10 pages.

Only short quotes plus a link to the store page end up in reports; full reviews are
never republished.
"""

import requests

from .config import Settings, http_headers, load_settings

SEARCH_URL = "https://itunes.apple.com/search"
REVIEWS_URL = ("https://itunes.apple.com/{country}/rss/customerreviews/page={page}/"
               "id={app_id}/sortby=mostrecent/json")
MAX_PAGES = 10


def _get_json(url: str, params: dict = None, settings: Settings = None) -> dict:
    settings = settings or load_settings()
    r = requests.get(url, params=params, headers=http_headers(settings), timeout=settings.http_timeout)
    r.raise_for_status()
    return r.json()


def search_apps(term: str, country: str = "us", limit: int = 5, settings: Settings = None) -> list:
    data = _get_json(SEARCH_URL, {"term": term, "entity": "software", "country": country, "limit": limit},
                     settings)
    return [{"app_id": a["trackId"], "name": a.get("trackName"), "developer": a.get("artistName"),
             "rating_count": a.get("userRatingCount") or 0,
             "average_rating": round(a.get("averageUserRating") or 0, 2),
             "price": a.get("formattedPrice"), "genre": a.get("primaryGenreName"),
             "url": a.get("trackViewUrl"), "country": country}
            for a in data.get("results", []) if a.get("trackId")]


def fetch_reviews(app_id: int, country: str = "us", pages: int = 3, settings: Settings = None) -> list:
    reviews = []
    for page in range(1, min(pages, MAX_PAGES) + 1):
        try:
            data = _get_json(REVIEWS_URL.format(country=country, page=page, app_id=app_id), settings=settings)
        except (requests.RequestException, ValueError):
            break  # the feed sometimes returns empty/HTML for an app; keep what we have
        entries = (data.get("feed") or {}).get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        # The first entry of page 1 can be app metadata, not a review.
        entries = [e for e in entries if "im:rating" in e]
        if not entries:
            break
        for e in entries:
            reviews.append({"stars": int(e["im:rating"]["label"]), "title": e["title"]["label"],
                            "body": e["content"]["label"], "version": (e.get("im:version") or {}).get("label"),
                            "date": (e.get("updated") or {}).get("label")})
    return reviews
