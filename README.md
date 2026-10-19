# NeedMiner

**Mine real user needs from app reviews — no Reddit, no API keys required.**

> Looking for a GummySearch alternative? GummySearch is shutting down; NeedMiner finds
> user needs from App Store reviews, Hacker News and Stack Exchange instead of Reddit.

Give it a product category ("budget app", "sleep tracker", "invoice maker") and one or more
countries. It reads what real users say about the existing apps and what developers complain
about in public communities, and returns a report you can act on:

- **App list with demand** — top App Store apps for the term in each country, with their total
  rating count (a proxy for market demand) and average rating.
- **Complaint types** — every review is classified by rules (pricing/subscription, bugs/crashes,
  ads, missing feature, accuracy, localization, support, privacy), with counts and shares.
- **Verbatim wishes** — sentences like *"I wish…"*, *"please add…"*, *"would be nice…"*, quoted
  briefly with a link to the store page. Happy 5-star users' wishes count too.
- **Willingness to pay** — reviews that say *"I'd pay"*, *"one-time"*, *"lifetime"*…
- **Developer community evidence** — counts of wish / pain / missing-docs phrases in Hacker News
  comments (official Algolia API) and Stack Exchange questions (official API 2.3), with links.
- **Opportunity score** — `log10(demand) × share of 1–2★ reviews × (1 + wish rate) × 10`.
- *Optional:* Google Trends yearly growth (`--trends`) and LLM grouping of evidence into
  concrete needs (`--llm`), where the model only points at evidence and **code does the counting**
  — a need is flagged **STRONG** only when it shows up in ≥2 independent sources, ≥2 apps, ≥6 texts
  and the category is not clearly declining.

Everything except `--llm` runs at zero cost. Output: Markdown + CSV (+ JSON).

## Why

Reddit-based pain-point tools depend on a data licence they may not get. needminer uses only
public, official, key-less endpoints:

| Source | Endpoint | Key needed |
| --- | --- | --- |
| Apple App Store search | iTunes Search API | no |
| App Store reviews | customer reviews RSS (most recent, 50/page) | no |
| Hacker News | hn.algolia.com API | no |
| Stack Exchange | api.stackexchange.com 2.3 (300 req/day anonymous) | optional `STACKEXCHANGE_KEY` |
| Google Trends (`--trends`) | unofficial `pytrends` package | no |
| Gemini (`--llm`) | Google GenAI SDK | `GEMINI_API_KEY` |

## Install

```bash
git clone https://github.com/happysproutstore-lang/needminer && cd needminer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # core: only depends on `requests`
pip install -e .[trends]    # optional: Google Trends
pip install -e .[llm]       # optional: Gemini grouping
```

Configuration is environment variables only. Copy `.env.example` and export the ones you need
(none are required for a basic run).

## Usage

```bash
needminer "budget app"                                  # US App Store + HN + Stack Exchange
needminer "budget app" --country us,gb,de --apps 5      # several countries
needminer "meditation" --country tr --pages 5           # non-English stores work too
needminer "invoice maker" --se-sites money,webapps --hn-count 200
needminer "sleep tracker" --trends --llm                # optional extras
needminer "budget app" --no-community --no-save         # store only, print to terminal
python -m needminer --help
```

Reports are written to `./reports/` (or `--out DIR` / `NEEDMINER_OUTPUT_DIR`):

- `<date>_<term>.md` — the human-readable report
- `<date>_<term>_apps.csv` — one row per app
- `<date>_<term>_wishes.csv` — one row per wish sentence (quote + store link)
- `<date>_<term>.json` — everything, for further processing

Network use per run is small: 1 search + `apps × pages` review requests per country, 1 Hacker
News request, 1 request per Stack Exchange site.

## Example output

Real run, 2026-10-19: `needminer "budget app" --country us --apps 3 --pages 2 --hn-count 50 --se-sites webapps,money`
(full files in [`examples/`](examples/)).

```markdown
| Country | Opportunity | Demand (ratings) | Reviews | 1-2 star | Wish rate | Willing to pay | Top complaints |
| --- | --- | --- | --- | --- | --- | --- | --- |
| us | 11.89 | 113,416 | 300 | 22% | 5% | 12 | pricing_subscription 8%, missing_feature 6%, support 4% |

## What users wish for (verbatim, short quotes)

- "This app is great but please add the option to add a merchant name." (5★, Budget app - spending tracker, us)
- "I wish theres a way to track debts with the same UI as the savings tracker, ..." (4★, Budget app - spending tracker, us)
- "I would love to see them add a yearly budget within this app where I can add line items like “Christmas” ..." (5★, EveryDollar, us)

## Developer community evidence

| Source | Scanned | Matched | Willing to pay | Phrase kinds |
| --- | --- | --- | --- | --- |
| hackernews | 50 | 8 | 1 | wish 5, pain 3, knowledge_loss 1 |
| stackexchange | 26 | 2 | 0 | pain 2 |
```

## Data use

- Reports contain **short quotes plus a link** to the source, never full review dumps.
- Stack Exchange content is CC BY-SA — keep the links when you republish.
- Google Trends access goes through the unofficial `pytrends` package; it is off by default and
  backs off for several hours after an HTTP 429.
- Respect each source's terms of use and rate limits; set `NEEDMINER_USER_AGENT` to identify
  yourself.

## Development

```bash
pip install -e .[dev]
pytest           # tests never touch the network
```

## License

MIT © 2026 HAPPYSPROUTSTORE LLC
