"""Command line entry point: `needminer "budget app" --country us,gb`."""

import argparse
import sys

from . import __version__
from .community import SE_DEFAULT_SITES
from .config import load_settings
from .report import to_markdown, write_reports
from .scanner import scan


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="needminer",
                                description="Find unmet user needs from App Store reviews, Hacker News and Stack Exchange.")
    p.add_argument("term", help='search term, e.g. "budget app"')
    p.add_argument("--country", default="us",
                   help="comma-separated App Store country codes (default: us), e.g. us,gb,de")
    p.add_argument("--apps", type=int, default=5, help="apps per country (default 5)")
    p.add_argument("--pages", type=int, default=3, help="review pages per app, 50 reviews each, max 10 (default 3)")
    p.add_argument("--no-community", action="store_true", help="skip Hacker News / Stack Exchange")
    p.add_argument("--se-sites", default=",".join(SE_DEFAULT_SITES),
                   help="comma-separated Stack Exchange sites (empty string to skip)")
    p.add_argument("--hn-count", type=int, default=100, help="Hacker News comments to scan (0 to skip)")
    p.add_argument("--trends", action="store_true", help="add Google Trends yearly growth (needs pytrends)")
    p.add_argument("--llm", action="store_true", help="group needs with Gemini (needs GEMINI_API_KEY)")
    p.add_argument("--out", default=None, help="output folder (default: $NEEDMINER_OUTPUT_DIR or ./reports)")
    p.add_argument("--no-save", action="store_true", help="print markdown only, write no files")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    countries = [c.strip().lower() for c in args.country.split(",") if c.strip()]
    se_sites = tuple(s.strip() for s in args.se_sites.split(",") if s.strip())
    result = scan(args.term, countries=countries, apps=args.apps, pages=args.pages,
                  community_sources=not args.no_community, se_sites=se_sites, hn_count=args.hn_count,
                  use_trends=args.trends, use_llm=args.llm or settings.llm_enabled, settings=settings)
    print(to_markdown(result))
    if not args.no_save:
        paths = write_reports(result, args.out or settings.output_dir)
        print("Saved:", ", ".join(paths.values()), file=sys.stderr)
    return 0 if result["stores"] or result["community"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
