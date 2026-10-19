"""Optional Google Trends yearly growth (last 12 months vs previous 12, from 5 years of weekly data).

Uses the unofficial `pytrends` package (install with `pip install .[trends]`). It is OFF by
default (`--trends` turns it on). After an HTTP 429 a cooldown file is written and no Trends
request is sent for NEED_SCANNER_TRENDS_COOLDOWN_HOURS, so we never hammer the endpoint.
"""

import json
import os
from datetime import datetime, timedelta

from .config import Settings, load_settings

MIN_VOLUME = 5.0  # Trends is 0-100; below this a % change is noise
RATE_LIMIT_LABEL = "trends_429"


def _is_429(err) -> bool:
    msg = f"{type(err).__name__} {err}"
    return "429" in msg or "TooManyRequests" in msg


def _in_cooldown(settings: Settings) -> bool:
    try:
        with open(settings.trends_state_file, encoding="utf-8") as f:
            last = json.load(f).get("last_429")
        return datetime.now() - datetime.fromisoformat(last) < timedelta(hours=settings.trends_cooldown_hours)
    except (OSError, ValueError, TypeError):
        return False


def _record_429(settings: Settings, err) -> None:
    try:
        os.makedirs(os.path.dirname(settings.trends_state_file) or ".", exist_ok=True)
        with open(settings.trends_state_file, "w", encoding="utf-8") as f:
            json.dump({"last_429": datetime.now().isoformat(timespec="seconds"), "error": str(err)[:200]}, f)
    except OSError:
        pass


def growth_from_series(series: list) -> dict:
    """Pure helper (tested): yearly change of a weekly 0-100 series."""
    last, prev = series[-52:], series[-104:-52]
    last_avg = sum(last) / len(last) if last else 0
    prev_avg = sum(prev) / len(prev) if prev else 0
    change = round((last_avg - prev_avg) / prev_avg * 100, 1) if prev_avg else None
    out = {"last_12m_avg": round(last_avg, 1), "prev_12m_avg": round(prev_avg, 1), "yearly_change_pct": change}
    if max(last_avg, prev_avg) < MIN_VOLUME:
        out["yearly_change_pct"] = None
        out["note"] = "volume too low, change not meaningful"
    return out


def yearly_growth(term: str, geo: str = "", hl: str = "en-US", settings: Settings = None) -> dict:
    settings = settings or load_settings()
    base = {"term": term, "geo": geo or "worldwide"}
    if _in_cooldown(settings):
        return {**base, "error": f"{RATE_LIMIT_LABEL}: cooldown active, not measured"}
    try:
        from pytrends.request import TrendReq
        client = TrendReq(hl=hl, tz=0)
        client.build_payload([term], timeframe="today 5-y", geo=geo)
        df = client.interest_over_time()
    except ImportError:
        return {**base, "error": "pytrends not installed (pip install .[trends])"}
    except Exception as e:  # noqa: BLE001 - 429 / network: signal is "unknown", not "zero"
        if _is_429(e):
            _record_429(settings, e)
            return {**base, "error": f"{RATE_LIMIT_LABEL}: {str(e)[:120]}"}
        return {**base, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    if df.empty or df[term].sum() == 0:
        return {**base, "error": "not enough search volume"}
    return {**base, **growth_from_series(df[term].tolist())}
