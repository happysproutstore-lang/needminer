"""Rule-based text analysis: complaint categories, wish sentences, willingness-to-pay.

No LLM is used here. Phrases are matched on "folded" text (lower case, accents removed,
punctuation turned into spaces) so the same rules work for English and Turkish reviews.
Add phrases for more languages by extending the lists below.
"""

import html
import re
import unicodedata

# Complaint categories -> phrases searched in folded text.
COMPLAINT_CATEGORIES = {
    "pricing_subscription": ["pahali", "abonelik", "ucretli", "ucret", "iade", "para ist", "odeme",
                             "expensive", "subscription", "refund", "price", "paywall", "charged"],
    "bugs_crashes": ["calismiyor", "acilmiyor", "hata ver", "coktu", "cokuyor", "donuyor", "kapaniyor",
                     "yuklenmiyor", "bug", "crash", "not working", "doesn t work", "doesnt work", "freez"],
    "ads": ["reklam", " ads", "advert"],
    "missing_feature": ["keske", " olsa", "olmasini isterdim", "eklenmeli", "eklenirse", "ekleyin",
                        "ekler misiniz", "yok mu", "olmali", "wish", "please add", "would be nice",
                        "would love", "would be great", "add an option", "should have", "should add",
                        "missing", " need a way", " need an option", "if only", "feature request"],
    "accuracy_quality": ["yanlis", "dogru degil", "sacma", "alakasiz", "kalitesiz", "tutarsiz",
                         "inaccurate", "wrong", "useless"],
    "localization": ["turkce", "language", "translation", "translate", "localization", "localisation"],
    "support": ["destek", "cevap vermiyor", "donus yok", "ulasamiyorum", "support", "no response"],
    "privacy_data": ["gizlilik", "kisisel veri", "hesabimi sil", "privacy", "my data"],
}
WISH_PHRASES = COMPLAINT_CATEGORIES["missing_feature"]
# Turkish "olsa" also appears in non-wish idioms ("nasil olsa" = anyway, "olsa da" = even if).
NOT_WISH = ["nasil olsa", "nasi olsa", "olsa da", "olsa bile", "sifir olsa", "olsaydim", "olsa olsa",
            # "wish I could give 0 stars" is a complaint, not a feature wish
            "wish i could give 0", "wish i could do 0", "wish i could give zero", "wish i could give no",
            "wish i could give negative", "wish i could rate 0", "wish i could rate zero"]

# Willingness to pay: proof that the user has budget, not only pain.
PAY_PHRASES = ["oderim", "odemeye hazir", "para veririm", "para vermeye", "param olsa", "satin alirim",
               "tek seferlik", "omur boyu", "would pay", "happy to pay", "willing to pay",
               "one time", "one-time", "lifetime", "i d pay", "id pay", "take my money"]

# Community (HN / Stack Exchange) phrases. A leading space anchors the match to a word start.
COMMUNITY_PHRASES = {
    "wish": [" i wish", " wish there was", " wish there were", " if only", " would be nice", " would love",
             " would pay", " i d pay", " happy to pay", " is there a tool", " is there any tool",
             " is there a way to", " why is there no", " why isn t there", " should exist", " keske"],
    "knowledge_loss": [" we lost", " lost all", " lost everything", " left the company", " tribal knowledge",
                       " bus factor", " nobody knows", " no one knows", " nobody remembers"],
    "missing_docs": [" nobody documents", " no one documents", " no documentation", " undocumented",
                     " not documented", " never documented", " outdated docs"],
    "pain": [" frustrat", " pain point", " painful", " nightmare", " drives me crazy", " i hate", " we hate",
             " struggl", " waste of time", " wasted hours", " wasted days", " no good way", " no good solution",
             " there is no good", " there s no good", " keeps breaking", " biggest problem"],
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def fold(text: str) -> str:
    """Lower-case, strip accents (incl. Turkish letters), punctuation -> space, pad with spaces."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower()
    text = text.translate(str.maketrans("çğıöşü", "cgiosu"))
    text = unicodedata.normalize("NFKD", text)
    return " " + "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text
                         if not unicodedata.combining(ch)) + " "


def is_wish(folded: str) -> bool:
    cleaned = folded
    for phrase in NOT_WISH:
        cleaned = cleaned.replace(phrase, " ")
    return any(p in cleaned for p in WISH_PHRASES)


def is_willing_to_pay(folded: str) -> bool:
    return any(p in folded for p in PAY_PHRASES)


def classify_review(title: str, body: str) -> list:
    folded = fold(f"{title or ''} {body or ''}")
    return [cat for cat, phrases in COMPLAINT_CATEGORIES.items()
            if (is_wish(folded) if cat == "missing_feature" else any(p in folded for p in phrases))]


def wish_sentences(text: str) -> list:
    """Sentences containing a wish phrase, returned verbatim (not folded)."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip() and is_wish(fold(s))]


def community_phrases(text: str) -> dict:
    """{kind: [matched phrase, ...]} for kinds that matched. Counting is done by code, not a model."""
    folded = fold(text)
    found = {}
    for kind, phrases in COMMUNITY_PHRASES.items():
        hits = [p.strip() for p in phrases if p in folded]
        if hits:
            found[kind] = hits
    return found


def matching_excerpt(text: str, limit: int = 400) -> str:
    """Only the sentences that contain a community phrase (else the start of the text)."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]
    relevant = [s for s in sentences if community_phrases(s)]
    return (" ".join(relevant) if relevant else (text or ""))[:limit]


def strip_html(text: str) -> str:
    """HN / Stack Exchange HTML body -> plain text."""
    text = re.sub(r"<\s*(p|br|li)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def short_quote(text: str, limit: int = 200) -> str:
    """Short quote for reports: we link to the source instead of republishing full reviews."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
