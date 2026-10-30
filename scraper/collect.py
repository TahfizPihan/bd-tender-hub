"""Collect tenders from all enabled sources and write docs/tenders.json.

Usage:
    python -m scraper.collect                 # run all enabled sources
    python -m scraper.collect --probe URL     # preview what the link heuristic finds on a page
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import bppa, browser, egp_browser, epaper, extract_ai, net, normalize, parsers, webpage, worldbank
from .net import fetch, robots_allows

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
OUT_FILE = ROOT / "docs" / "tenders.json"
COLLECTOR_VERSION = 3


def run_source(src, now, log=print):
    if src["type"] == "rss":
        raw = parsers.parse_rss(fetch(src["url"]), src)
        if src.get("require_tender_word"):
            raw = [r for r in raw if parsers.TENDER_WORDS.search((r.get("title") or "") + " " + (r.get("summary") or ""))]
    elif src["type"] == "html_links":
        if not robots_allows(src["url"]):
            raise RuntimeError("blocked by robots.txt")
        raw = parsers.parse_html_links(fetch(src["url"]), src["url"], src)
    else:
        raise ValueError(f"unknown source type {src['type']}")
    return [normalize.build_record(src, r, now) for r in raw]


def load_existing():
    if OUT_FILE.exists():
        try:
            return json.loads(OUT_FILE.read_text(encoding="utf-8")).get("tenders", [])
        except (ValueError, OSError):
            pass
    return []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", metavar="URL", help="preview heuristic link extraction on a page")
    ap.add_argument("--no-ai", action="store_true", help="skip Gemini enrichment")
    args = ap.parse_args(argv)

    if args.probe:
        items = parsers.parse_html_links(fetch(args.probe), args.probe)
        print(f"{len(items)} candidate link(s) on {args.probe}")
        for it in items[:40]:
            print(f"- {it['title'][:90]}\n    {it['link']}")
        return 0

    now = datetime.now(timezone.utc)
    sources = [s for s in json.loads(SOURCES_FILE.read_text(encoding="utf-8")) if s.get("enabled")]
    sources += epaper.inbox_sources()
    existing = load_existing()
    page_state = epaper.load_state()
    budget = [int(os.environ.get("MAX_PAGES_PER_RUN", "30"))]
    fresh, status = [], []
    for src in sources:
        try:
            if src["type"] == "epaper_pages":
                recs = epaper.run_source(src, now, page_state, budget)
            elif src["type"] == "ai_page":
                recs = webpage.run_source(src, now, page_state, budget)
            elif src["type"] == "browser_page":
                recs = webpage.run_source(src, now, page_state, budget, fetcher=browser.fetch_html)
            elif src["type"] == "worldbank":
                recs = worldbank.run_source(src, now)
            elif src["type"] == "bppa":
                recs = bppa.run_source(src, now, existing=existing)
            elif src["type"] == "egp_browser":
                recs = egp_browser.run_source(src, now, existing=existing)
            else:
                recs = run_source(src, now)
            fresh.extend(recs)
            status.append({"id": src["id"], "name": src["name"], "ok": True, "count": len(recs),
                           **({"experimental": True} if src.get("experimental") else {})})
            print(f"[ok]   {src['id']}: {len(recs)} item(s)")
        except (epaper.Skipped, webpage.Skipped) as e:
            status.append({"id": src["id"], "name": src["name"], "ok": True, "count": 0, "note": str(e)})
            print(f"[skip] {src['id']}: {e}")
        except Exception as e:  # one broken source must not stop the others
            status.append({"id": src["id"], "name": src["name"], "ok": False, "count": 0,
                           "error": str(e)[:300], **({"experimental": True} if src.get("experimental") else {})})
            print(f"[fail] {src['id']}: {e}", file=sys.stderr)
        time.sleep(1)

    if sources and not any(s["ok"] for s in status):
        print("All sources failed; keeping previous data untouched.", file=sys.stderr)
        return 1

    epaper.save_state(page_state, now)
    merged = normalize.merge(existing, fresh, now)
    if not args.no_ai:
        extract_ai.enrich(merged)
    merged = normalize.prune(merged, now)
    merged.sort(key=lambda r: r["first_seen"], reverse=True)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "generated_at": now.isoformat(timespec="seconds"),
        "collector_version": COLLECTOR_VERSION,
        "count": len(merged),
        "sources": status,
        "tenders": merged,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(merged)} tender(s) to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
