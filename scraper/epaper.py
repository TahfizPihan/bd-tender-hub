"""Newspaper tender pages (images / PDFs) -> structured tenders via Gemini.

A source of type "epaper_pages" lists page URLs (or a url_template with {yyyy} {mm} {dd}
{page}). Each page is downloaded on the collector's machine, read by the AI, and only the
extracted facts (title, organization, deadline...) are stored, with a link back to the page.
The page image itself is never saved or republished. Pages are processed once.
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import extract_ai, normalize

BD = ZoneInfo("Asia/Dhaka")
MAX_BYTES = 10_000_000
ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "processed_pages.json"
INBOX_FILE = ROOT / "inbox.txt"
UA = {"User-Agent": "BD-Tender-Hub/0.1 (open-source tender index; links back to originals)"}


class Skipped(Exception):
    """Source intentionally not run (e.g. no API key)."""


def expand_urls(src, now=None):
    now = (now or datetime.now(BD)).astimezone(BD)
    urls = []
    tpl = src.get("url_template")
    if tpl:
        for p in (src.get("pages") or [1]):
            try:
                urls.append(tpl.format(yyyy=f"{now:%Y}", mm=f"{now:%m}", dd=f"{now:%d}", page=p))
            except (KeyError, IndexError) as e:
                raise ValueError(f"bad url_template placeholder: {e}")
    urls += list(src.get("urls") or [])
    return urls


def fetch_page(url):
    """Download an image/PDF. Returns (bytes, mime). Refuses HTML pages."""
    r = requests.get(url, headers=UA, timeout=45, stream=True)
    r.raise_for_status()
    ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if "html" in ct:
        raise ValueError("URL is a web page, not an image or PDF")
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("file larger than 10 MB")
    if "pdf" in ct or url.lower().split("?")[0].endswith(".pdf") or data[:4] == b"%PDF":
        return data, "application/pdf"
    if ct in ("image/jpeg", "image/png", "image/webp"):
        return data, ct
    if data[:3] == b"\xff\xd8\xff":
        return data, "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data, "image/png"
    raise ValueError(f"unsupported content type {ct or 'unknown'}")


def clean_items(items, link):
    """Validate AI output; return raw dicts for normalize.build_record."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        title = re.sub(r"\s+", " ", str(it.get("title") or "")).strip()
        if len(title) < 6:
            continue
        deadline = str(it.get("deadline") or "")
        try:
            date.fromisoformat(deadline)
        except ValueError:
            deadline = None
        org = re.sub(r"\s+", " ", str(it.get("organization") or "")).strip() or None
        loc = str(it.get("location") or "").strip() or None
        val = it.get("estimated_value_bdt")
        raw = {"title": title[:300], "organization": org[:200] if org else None,
               "deadline": deadline, "link": link,
               "summary": ("Location: " + loc) if loc else "", "ai": True}
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            raw["value_bdt"] = val
        if it.get("category") in extract_ai.CATEGORIES:
            raw["category"] = it["category"]
        out.append(raw)
    return out


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state, now, keep_days=21):
    cutoff = (now - timedelta(days=keep_days)).isoformat()
    state = {u: t for u, t in state.items() if t >= cutoff}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def inbox_sources():
    """inbox.txt: one 'URL | Newspaper name' per line (# comments allowed)."""
    if not INBOX_FILE.exists():
        return []
    srcs = []
    for line in INBOX_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, label = [p.strip() for p in line.partition("|")]
        if url.startswith("http"):
            srcs.append({"id": "inbox", "name": label or "Newspaper (manual)", "type": "epaper_pages",
                         "urls": [url], "kind": "newspaper", "enabled": True})
    return srcs


def run_source(src, now, state, budget, fetcher=fetch_page, extractor=extract_ai.extract_page,
               log=print, require_key=True):
    """Process a source's pages. `budget` is a one-item list: pages left this run."""
    if require_key and not os.environ.get("GEMINI_API_KEY"):
        raise Skipped("skipped: needs GEMINI_API_KEY to read newspaper pages")
    records = []
    for url in expand_urls(src, now):
        if url in state:
            continue
        if budget[0] <= 0:
            log(f"  page budget used up; remaining pages wait for the next run ({src['id']})")
            break
        try:
            data, mime = fetcher(url)
        except (requests.RequestException, ValueError) as e:
            log(f"  [skip page] {url}: {e}")   # e.g. 404 because today's page isn't out yet
            continue
        budget[0] -= 1
        try:
            items = extractor(data, mime)
        except Exception as e:
            log(f"  [AI failed] {url}: {e}")
            continue
        state[url] = now.isoformat(timespec="seconds")
        for raw in clean_items(items, url):
            rec = normalize.build_record(src, raw, now)
            rec["via"] = "newspaper"
            rec["ai_extracted"] = True
            rec["needs_ai"] = False
            if raw.get("category"):
                rec["category"] = raw["category"]
            if raw.get("value_bdt") is not None:
                rec["value_bdt"] = raw["value_bdt"]
            records.append(rec)
    return records
