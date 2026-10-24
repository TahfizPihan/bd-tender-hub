"""Generic listing pages (bank / NGO tender or notice boards) read by AI.

Per-site HTML selectors are fragile, so instead the page is fetched, turned into text with the
links kept inline, and Gemini lists the tender notices on it. A page whose text hasn't changed
since the last run is skipped, so unchanged pages cost nothing.
"""
import hashlib
import re
from datetime import timedelta
from urllib.parse import urljoin

import requests

from . import extract_ai, net, normalize, parsers
from .epaper import Skipped, expand_urls  # noqa: F401  (Skipped re-exported for collect.py)
import os

MIN_TEXT = 200  # shorter than this usually means the page is built by JavaScript


def clean_items(items, page_url):
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        title = re.sub(r"\s+", " ", str(it.get("title") or "")).strip()
        if len(title) < 8:
            continue
        link = str(it.get("link") or "").strip()
        link = urljoin(page_url, link) if link else page_url
        if not link.startswith(("http://", "https://")):
            link = page_url
        raw = {"title": title[:300], "link": link}
        org = re.sub(r"\s+", " ", str(it.get("organization") or "")).strip()
        raw["organization"] = org[:200] or None
        for f in ("deadline", "published"):
            v = str(it.get(f) or "")
            raw[f] = v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and normalize.find_dates(v) else None
        if it.get("category") in extract_ai.CATEGORIES:
            raw["category"] = it["category"]
        out.append(raw)
    return out


def run_source(src, now, state, budget, fetcher=net.fetch, extractor=extract_ai.extract_listing,
               robots=net.robots_allows, log=print, require_key=True):
    if require_key and not os.environ.get("GEMINI_API_KEY"):
        raise Skipped("skipped: needs GEMINI_API_KEY to read web pages")
    urls = [src["url"]] if src.get("url") else []
    urls += expand_urls(src, now)
    records, failures = [], 0
    for url in urls:
        if not robots(url):
            log(f"  [skip] {url}: disallowed by robots.txt")
            failures += 1
            continue
        try:
            html = fetcher(url)
        except requests.RequestException as e:
            log(f"  [skip page] {url}: {e}")
            failures += 1
            continue
        text = parsers.html_to_text_with_links(html, url)
        if len(text) < MIN_TEXT:
            log(f"  [skip page] {url}: almost no text (page may need JavaScript)")
            failures += 1
            continue
        key = f"{url}#{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"
        if key in state:
            continue                                   # unchanged since last time
        if budget[0] <= 0:
            log(f"  page budget used up; {url} waits for the next run")
            break
        budget[0] -= 1
        try:
            items = extractor(text, url, now.astimezone(normalize.BD).date().isoformat())
        except Exception as e:
            log(f"  [AI failed] {url}: {e}")
            failures += 1
            continue
        state[key] = now.isoformat(timespec="seconds")
        for raw in clean_items(items, url):
            rec = normalize.build_record(src, raw, now)
            rec["via"] = "webpage"
            rec["ai_extracted"] = True
            rec["needs_ai"] = False
            if raw.get("category"):
                rec["category"] = raw["category"]
            records.append(rec)
    if failures and failures == len(urls):
        raise RuntimeError("no page could be read")
    return records
