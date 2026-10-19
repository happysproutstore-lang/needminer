"""Markdown + CSV + JSON output."""

import csv
import json
import os
import re

from .text import fold


def _pct(x) -> str:
    return f"{round((x or 0) * 100)}%"


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "/").replace("\n", " ")


def to_markdown(r: dict, max_wishes: int = 15) -> str:
    out = [f"# Need scan: \"{r['term']}\"", "",
           f"Generated {r['generated_at']} · countries: {', '.join(r['countries'])} · method: {r['method']}", ""]

    if r["stores"]:
        out += ["## Summary by store", "",
                "| Country | Opportunity | Demand (ratings) | Reviews | 1-2 star | Wish rate | Willing to pay | Top complaints |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in r["stores"]:
            top = ", ".join(f"{k} {_pct(v['share'])}" for k, v in list(s["complaint_categories"].items())[:3])
            out.append(f"| {s['country']} | {s['opportunity_score']} | {s['demand_rating_count']:,} | "
                       f"{s['reviews_analyzed']} | {_pct(s['low_star_share'])} | {_pct(s['wish_rate'])} | "
                       f"{s['willing_to_pay']} | {top} |")

        out += ["", "## Apps (rating count = demand)", "",
                "| Country | App | Developer | Ratings | Avg | Reviews read | 1-2 star | Top complaints |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in r["stores"]:
            for a in s["apps"]:
                top = ", ".join(list(a.get("complaint_categories", {}))[:3])
                name = f"[{_cell(a['name'])}]({a['url']})" if a.get("url") else _cell(a["name"])
                out.append(f"| {s['country']} | {name} | {_cell(a['developer'])} | {a['rating_count']:,} | "
                           f"{a['average_rating']} | {a.get('reviews_fetched', 0)} | {_pct(a.get('low_star_share'))} | {top} |")

    if r.get("needs"):
        out += ["", "## Unmet needs (LLM grouping, evidence counted by code)", ""]
        for n in r["needs"]:
            flag = "**STRONG** " if n["strong_signal"] else ""
            out.append(f"- {flag}{n['need']} — {n['evidence_count']} texts, {n['source_count']} sources "
                       f"({', '.join(n['sources'])}), {n['willing_to_pay']} willing to pay")

    wishes = [w for s in r["stores"] for w in s["wishes"]]
    if wishes:
        out += ["", "## What users wish for (verbatim, short quotes)", ""]
        for w in wishes[:max_wishes]:
            link = f" — [store page]({w['url']})" if w.get("url") else ""
            out.append(f"- \"{w['quote']}\" ({w['stars']}★, {w['app']}, {w['country']}){link}")

    if r.get("community"):
        out += ["", "## Developer community evidence", "",
                "| Source | Scanned | Matched | Willing to pay | Phrase kinds |", "| --- | --- | --- | --- | --- |"]
        for name, c in r["community"].items():
            kinds = ", ".join(f"{k} {v}" for k, v in c["phrase_kinds"].items())
            out.append(f"| {name} | {c['scanned']} | {c['matched']} | {c['willing_to_pay']} | {kinds} |")
        for name, c in r["community"].items():
            if c["examples"]:
                out += ["", f"### {name} examples", ""]
                out += [f"- \"{e['quote']}\" — [source]({e['url']})" for e in c["examples"][:3]]
        out += ["", "_Stack Exchange content is licensed CC BY-SA; follow the links for full text and attribution._"]

    if r.get("trends"):
        out += ["", "## Google Trends (yearly growth)", ""]
        for t in r["trends"]:
            if t.get("error"):
                out.append(f"- {t['term']} ({t['geo']}): not measured — {t['error']}")
            else:
                change = "n/a" if t["yearly_change_pct"] is None else f"{t['yearly_change_pct']:+}%"
                out.append(f"- {t['term']} ({t['geo']}): {change} (last 12m avg {t['last_12m_avg']} vs "
                           f"{t['prev_12m_avg']}){' — ' + t['note'] if t.get('note') else ''}")

    if r.get("errors"):
        out += ["", "## Warnings", ""] + [f"- {e}" for e in r["errors"]]
    return "\n".join(out) + "\n"


def _slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", fold(term).strip())[:40].strip("_") or "scan"


def write_reports(r: dict, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"{r['generated_at'].replace(' ', '_').replace(':', '')}_{_slug(r['term'])}")
    paths = {"markdown": base + ".md", "json": base + ".json", "apps_csv": base + "_apps.csv",
             "wishes_csv": base + "_wishes.csv"}
    with open(paths["markdown"], "w", encoding="utf-8") as f:
        f.write(to_markdown(r))
    with open(paths["json"], "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    with open(paths["apps_csv"], "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "app", "developer", "rating_count", "average_rating", "price", "genre",
                    "reviews_fetched", "low_star_share", "top_complaints", "url"])
        for s in r["stores"]:
            for a in s["apps"]:
                w.writerow([s["country"], a["name"], a["developer"], a["rating_count"], a["average_rating"],
                            a.get("price"), a.get("genre"), a.get("reviews_fetched", 0), a.get("low_star_share"),
                            ";".join(a.get("complaint_categories", {})), a.get("url")])
    with open(paths["wishes_csv"], "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "app", "stars", "quote", "url"])
        for s in r["stores"]:
            for x in s["wishes"]:
                w.writerow([x["country"], x["app"], x["stars"], x["quote"], x["url"]])
    return paths
