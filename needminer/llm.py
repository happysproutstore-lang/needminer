"""Optional LLM grouping (OFF by default; `--llm` or NEEDMINER_LLM=1 turns it on).

The model only returns need statements plus the NUMBERS of the texts that support them.
Every count (evidence, willingness to pay, apps, sources) is computed by code from those
numbers; invalid numbers are dropped, so the model cannot invent evidence.

Requires `pip install .[llm]` and GEMINI_API_KEY. Default model: gemini-flash-lite-latest
(a few cents per report at most).
"""

import json

from .config import Settings, load_settings

STRONG_MIN_SOURCES = 2
STRONG_MIN_APPS = 2
STRONG_MIN_EVIDENCE = 6
TREND_DECLINE_THRESHOLD = -15.0

REVIEW_PROMPT = """Below are REAL user texts about "{term}" (numbered; low-star complaints, wishes and
willingness-to-pay sentences). Find concrete needs that existing products do NOT meet.

Rules:
- Each need must be concrete and actionable (not "a better app"; e.g. "one-time purchase instead of subscription").
- For each need list the NUMBERS of the texts that support it. Only count texts that really express it; do not invent.
- Skip needs supported by fewer than 2 texts. At most 8 needs.
- type: "feature" | "pricing_model" | "quality_accuracy" | "ads" | "localization" | "trust_support" | "workflow" | "other"
- Write the needs in English.

Return JSON only: {{"needs": [{{"need": "...", "type": "...", "support": [3, 17, 42]}}]}}

TEXTS:
{texts}"""

MERGE_PROMPT = """Below are need clusters for "{term}" from DIFFERENT sources. Each line: [number] (source) need.
Some describe the SAME need in different words. Group the ones that describe the same need; do not merge
different needs. For each group write one short, concrete English need sentence and the cluster NUMBERS.
Single-cluster groups are allowed. JSON only: {{"groups": [{{"need": "...", "clusters": [0, 4, 9]}}]}}

CLUSTERS:
{clusters}"""

_CLIENT = None


def gemini_call(prompt: str, settings: Settings = None) -> str:
    """Default LLM callable. Tests inject their own `llm_call` instead."""
    global _CLIENT
    settings = settings or load_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set (needed only for --llm)")
    if _CLIENT is None:
        from google import genai  # optional dependency
        _CLIENT = genai.Client(api_key=settings.gemini_api_key)
    r = _CLIENT.models.generate_content(model=settings.gemini_model, contents=prompt,
                                        config={"response_mime_type": "application/json"})
    return r.text


def cluster_needs(term: str, evidence: list, llm_call=None, max_texts: int = 180) -> list:
    """evidence items: {"source", "stars", "pay", "text"}. Returns clusters sorted by evidence count."""
    items = sorted(evidence or [], key=lambda h: (not h["pay"], h["stars"]))[:max_texts]
    if len(items) < 4:
        return []
    texts = "\n".join(f"[{i}] ({h['stars']}*) {h['text']}" for i, h in enumerate(items))
    llm_call = llm_call or gemini_call
    try:
        data = json.loads(llm_call(REVIEW_PROMPT.format(term=term, texts=texts)))
    except (ValueError, TypeError):
        return []
    out = []
    for n in (data.get("needs", []) if isinstance(data, dict) else []):
        if not isinstance(n, dict) or not n.get("need"):
            continue
        support = sorted({i for i in n.get("support") or [] if isinstance(i, int) and 0 <= i < len(items)})
        if len(support) < 2:
            continue
        out.append({"need": n["need"], "type": n.get("type", "other"), "evidence_count": len(support),
                    "willing_to_pay": sum(items[i]["pay"] for i in support),
                    "apps": sorted({items[i]["source"] for i in support}),
                    "quotes": [f"({items[i]['stars']}* {items[i]['source']}) {items[i]['text'][:200]}"
                               for i in support[:3]]})
    return sorted(out, key=lambda x: -x["evidence_count"])


def merge_clusters(term: str, source_clusters: dict, trend: list = None, llm_call=None) -> list:
    """source_clusters: {"appstore_us": [cluster, ...], "hackernews": [...], ...}.

    A need is a STRONG signal when it appears in >= STRONG_MIN_SOURCES independent sources,
    from >= STRONG_MIN_APPS apps/sites, with >= STRONG_MIN_EVIDENCE texts, and the category is not
    clearly declining in Trends.
    """
    flat = [(src, c) for src, clusters in source_clusters.items() for c in (clusters or [])]
    if not flat:
        return []
    llm_call = llm_call or gemini_call
    lines = "\n".join(f"[{i}] ({src}) {c['need']}" for i, (src, c) in enumerate(flat))
    try:
        data = json.loads(llm_call(MERGE_PROMPT.format(term=term, clusters=lines)))
        groups = data.get("groups", []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001 - broken JSON / API error: no grouping, so no invented strong signal
        groups = [{"need": c["need"], "clusters": [i]} for i, (_, c) in enumerate(flat)]

    declining = any((t or {}).get("yearly_change_pct") is not None
                    and t["yearly_change_pct"] <= TREND_DECLINE_THRESHOLD for t in (trend or []))
    used, out = set(), []
    for g in groups:
        if not isinstance(g, dict):
            continue
        idx = sorted({i for i in g.get("clusters") or [] if isinstance(i, int) and 0 <= i < len(flat)} - used)
        if not idx:
            continue
        used.update(idx)  # a cluster is never counted in two groups
        sources = sorted({flat[i][0] for i in idx})
        apps = sorted({a for i in idx for a in flat[i][1].get("apps", [])})
        evidence = sum(flat[i][1]["evidence_count"] for i in idx)
        strong = (len(sources) >= STRONG_MIN_SOURCES and len(apps) >= STRONG_MIN_APPS
                  and evidence >= STRONG_MIN_EVIDENCE and not declining)
        out.append({"need": g.get("need") or flat[idx[0]][1]["need"], "strong_signal": strong,
                    "sources": sources, "source_count": len(sources), "app_count": len(apps),
                    "apps": apps[:8], "evidence_count": evidence,
                    "willing_to_pay": sum(flat[i][1].get("willing_to_pay", 0) for i in idx),
                    "types": sorted({flat[i][1].get("type", "other") for i in idx}),
                    "quotes": [q for i in idx for q in flat[i][1].get("quotes", [])][:4]})
    return sorted(out, key=lambda x: (not x["strong_signal"], -x["source_count"], -x["evidence_count"]))
