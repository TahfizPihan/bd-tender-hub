"""Optional AI enrichment using the Gemini free tier.

Only runs when GEMINI_API_KEY is set. It fills in missing organization /
deadline / category for tenders the rules couldn't parse (messy text, PDFs).
Each tender is tried at most once, and a per-run cap keeps you inside the
free-tier limits. Free-tier model names and limits change; override the model
with the GEMINI_MODEL environment variable if needed.
"""
import base64
import json
import os
import re

import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_PDF_BYTES = 4_000_000
CATEGORIES = ["Civil works", "ICT", "Furniture", "Medical", "Consultancy",
              "Electrical", "Vehicles", "Goods", "Other"]

PROMPT = """You extract structured data from a Bangladesh procurement/tender notice
(English or Bangla). Reply with JSON only, using exactly these keys:
{"organization": string|null, "deadline": "YYYY-MM-DD"|null, "category": one of %s,
 "estimated_value_bdt": number|null, "location": string|null}
Use null when the notice does not state a value. Never guess. The deadline is the
last date for submitting tenders/proposals.

NOTICE:
%s
"""


def _call(parts, key):
    r = requests.post(
        ENDPOINT.format(model=MODEL),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": parts}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _pdf_part(url):
    try:
        r = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "BD-Tender-Hub/0.1"})
        r.raise_for_status()
        data = r.raw.read(MAX_PDF_BYTES + 1, decode_content=True)
        if len(data) > MAX_PDF_BYTES:
            return None
        return {"inline_data": {"mime_type": "application/pdf",
                                "data": base64.b64encode(data).decode()}}
    except requests.RequestException:
        return None


def enrich(records, max_items=25, log=print):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log("AI enrichment skipped (no GEMINI_API_KEY).")
        return 0
    done = 0
    for rec in records:
        if done >= max_items:
            break
        if not rec.get("needs_ai") or rec.get("ai_tried"):
            continue
        text = f"Title: {rec['title']}\nContext: {rec.get('summary', '')}\nLink: {rec.get('link')}"
        parts = [{"text": PROMPT % (", ".join(CATEGORIES), text)}]
        if rec.get("link") and re.search(r"\.pdf($|\?)", rec["link"], re.I):
            pdf = _pdf_part(rec["link"])
            if pdf:
                parts.append(pdf)
        rec["ai_tried"] = True
        done += 1
        try:
            out = _call(parts, key)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            log(f"AI extraction failed for {rec['id']}: {e}")
            continue
        if not rec.get("organization") and out.get("organization"):
            rec["organization"] = str(out["organization"])[:200]
        if not rec.get("deadline") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(out.get("deadline") or "")):
            rec["deadline"] = out["deadline"]
        if rec.get("category") == "Other" and out.get("category") in CATEGORIES:
            rec["category"] = out["category"]
        for src, dst in (("estimated_value_bdt", "value_bdt"), ("location", "location")):
            if out.get(src) is not None:
                rec[dst] = out[src]
        rec["ai_extracted"] = True
        rec["needs_ai"] = not (rec.get("deadline") and rec.get("organization"))
    log(f"AI enrichment processed {done} tender(s).")
    return done


PAGE_PROMPT = """This is one page from a Bangladeshi newspaper (Bangla and/or English).
Find EVERY tender, e-tender, EOI, RFQ/RFP, lease or auction notice on it. Ignore all other ads.
Reply with JSON only: an array of objects, one per notice, with exactly these keys:
{"title": string, "organization": string|null, "deadline": "YYYY-MM-DD"|null,
 "category": one of %s, "estimated_value_bdt": number|null, "location": string|null}
- title: what is being procured, short, in the notice's own language.
- organization: the caller/procuring entity.
- deadline: last date to submit/drop bids, converted to YYYY-MM-DD (Bangla digits and
  Bangla months must be converted). Use null if not clearly stated.
- Never guess or invent a value. If the page has no tender notices, reply [].
"""


def extract_page(data, mime, retries=1):
    """Extract all tender notices from one newspaper page (image or PDF bytes)."""
    import time
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    parts = [{"text": PAGE_PROMPT % ", ".join(CATEGORIES)},
             {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}]
    for attempt in range(retries + 1):
        try:
            out = _call(parts, key)
            break
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < retries:
                time.sleep(35)   # free-tier rate limit: wait and retry once
                continue
            raise
    if isinstance(out, dict):
        out = out.get("tenders") or out.get("notices") or []
    return out if isinstance(out, list) else []


LISTING_PROMPT = """Below is the text of a web page from a Bangladeshi organization. Links appear as
`label <url>`; table rows are written as `cell | cell | cell`.
Find every tender, RFP/RFQ, EOI, vendor-enlistment or auction/sale notice listed. Ignore menus,
news, jobs and other content. Reply with JSON only: an array of objects with exactly these keys:
{"title": string, "organization": string|null, "deadline": "YYYY-MM-DD"|null,
 "published": "YYYY-MM-DD"|null, "category": one of %s, "link": string|null}
- link: copy the absolute URL (inside <...>) belonging to that notice's row or title exactly; null if none.
- Dates may be DD-MM-YYYY or written out; convert to YYYY-MM-DD. Today is %s.
- deadline is the last date to submit; null if not clearly stated. Never guess or invent anything.
- If the page lists no tender notices, reply [].
%s
PAGE URL: %s
PAGE TEXT:
%s
"""


def extract_listing(text, page_url, today, retries=1, focus=None):
    """Extract tender notices from the text of a listing page."""
    import time
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    focus_line = ("- Only include notices that concern %s; skip the rest." % focus) if focus else ""
    parts = [{"text": LISTING_PROMPT % (", ".join(CATEGORIES), today, focus_line, page_url, text)}]
    for attempt in range(retries + 1):
        try:
            out = _call(parts, key)
            break
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < retries:
                time.sleep(35)
                continue
            raise
    if isinstance(out, dict):
        out = out.get("tenders") or out.get("notices") or []
    return out if isinstance(out, list) else []
