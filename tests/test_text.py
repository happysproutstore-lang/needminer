from needminer import text


def test_classify_pricing():
    assert text.classify_review("", "The subscription is way too expensive") == ["pricing_subscription"]


def test_classify_multiple_categories_turkish():
    cats = set(text.classify_review("", "Açılmıyor. Keşke Türkçe olsa"))
    assert cats == {"bugs_crashes", "missing_feature", "localization"}


def test_positive_review_has_no_complaint():
    assert text.classify_review("Great", "Love this app") == []


def test_wish_sentences_verbatim():
    assert text.wish_sentences("Great app. I wish it had a dark mode! Thanks.") == ["I wish it had a dark mode!"]


def test_turkish_idioms_are_not_wishes():
    assert text.wish_sentences("Nası olsa randevu alınmıyor. Bazı hatalar olsa da fena değil.") == []


def test_willing_to_pay():
    assert text.is_willing_to_pay(text.fold("I would pay for a one-time version"))
    assert text.is_willing_to_pay(text.fold("Param olsa satın alırım"))
    assert not text.is_willing_to_pay(text.fold("Too expensive"))


def test_community_phrases_word_start():
    found = text.community_phrases("When she left the company we lost years of context. I wish there was a tool.")
    assert "wish" in found and "knowledge_loss" in found
    assert text.community_phrases("kiwish fruit") == {}


def test_strip_html():
    out = text.strip_html("<p>Nobody documents the &quot;why&quot;.</p><p>Next</p>")
    assert "<p>" not in out and 'the "why".' in out and out.endswith("Next")


def test_short_quote_truncates():
    q = text.short_quote("word " * 100, limit=50)
    assert len(q) <= 50 and q.endswith("…")


def test_zero_star_and_plain_need_are_not_wishes():
    assert text.wish_sentences("Wish I could do 0 stars.") == []
    assert text.wish_sentences("This app has everything I need and is simple.") == []
    assert text.wish_sentences("We need a way to export data.") == ["We need a way to export data."]
