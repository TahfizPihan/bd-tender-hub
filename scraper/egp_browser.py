"""e-GP "eTenders" public list (https://www.eprocure.gov.bd/resources/common/StdTenderSearch.jsp?h=t).

The list is filled in by JavaScript after the page loads, which is why a plain download sees an
empty table. A headless browser loads the page, reads the rendered table (login-free, no CAPTCHA),
and clicks "Next" for a limited number of pages with a pause between pages.

Columns on the page: Tender/Proposal ID + reference no + status | procurement nature + title |
ministry / division / organization / procuring entity | type + method | publishing + closing date.
Rows are matched by header text, not fixed positions, and a small debug file
(data/egp_debug.txt) is written every run so the parser can be tuned if the layout differs.
"""
import json
import re
import time
from pathlib import Path

from . import normalize

DEFAULT_URL = "https://www.eprocure.gov.bd/resources/common/StdTenderSearch.jsp?h=t"
DETAIL = "https://www.eprocure.gov.bd/resources/common/ViewTender.jsp?id={id}&h=t"
DEBUG_FILE = Path(__file__).resolve().parent.parent / "data" / "egp_debug.txt"

STATUS_WORDS = re.compile(r"^(live|processing|approved|cancelled|canceled|published|public|closed|open|new)$", re.I)
TIME_RX = re.compile(r"\b(\d{1,2}:\d{2}(?:\s*[AP]M)?)\b", re.I)

JS_TABLE = """() => {
  const clean = s => (s || '').replace(/\\u00a0/g, ' ').trim();
  // the page nests tables for layout: use the innermost table that holds the results
  const tables = [...document.querySelectorAll('table')].filter(t => !t.querySelector('table'));
  for (const t of tables) {
    const trs = [...t.rows];
    if (!trs.length) continue;
    const headers = [...trs[0].cells].map(c => clean(c.innerText));
    const h = headers.join(' | ').toLowerCase();
    if (!(/title/.test(h) && /(closing|publishing)/.test(h))) continue;
    const rows = [];
    for (const tr of trs.slice(1)) {
      const cells = [...tr.cells].filter(c => c.tagName === 'TD');
      if (cells.length < 4) continue;
      const a = tr.querySelector('a[href]');
      rows.push({cells: cells.map(c => clean(c.innerText)), href: a ? a.getAttribute('href') : null});
    }
    return {headers, rows};
  }
  return null;
}"""

JS_NEXT = """() => {
  const clean = e => ((e.innerText || e.value || '') + '').trim();
  const ok = e => !e.disabled && !/disabled/i.test(e.className || '') && !e.closest('.disabled,[disabled]');
  const all = [...document.querySelectorAll('a,button,input[type=button],input[type=submit],span,li')]
    .filter(e => /^next\\b/i.test(clean(e)) && ok(e));
  all.sort((x, y) => (x.tagName === 'A' ? 0 : 1) - (y.tagName === 'A' ? 0 : 1));
  const n = all[0];
  if (n) { n.click(); return true; }
  return false;
}"""

JS_PAGE_NO = """() => { const m = /Page\\s+(\\d+)\\s+of\\s+(\\d+)/i.exec(document.body.innerText); return m ? [+m[1], +m[2]] : null; }"""

JS_FORM_DUMP = """() => [...document.querySelectorAll('input,select,textarea')].filter(e => e.type !== 'hidden' || /page|size|row|start|offset/i.test(e.name || e.id || ''))
  .map(e => (e.tagName + ' name=' + (e.name || '') + ' id=' + (e.id || '') + ' type=' + (e.type || '') +
     (e.tagName === 'SELECT' ? ' options=' + [...e.options].slice(0, 12).map(o => o.value + ':' + o.text.trim()).join('/') : '') +
     (e.type === 'hidden' ? ' value=' + String(e.value).slice(0, 20) : ''))).slice(0, 60)"""

JS_PAGER_HTML = """() => { const e = [...document.querySelectorAll('*')].find(x => x.children.length < 12 && /Next\\s*[›>]/.test(x.innerText || '') && /Previous/.test(x.innerText || '') && (x.innerText || '').length < 80);
  return e ? e.outerHTML.slice(0, 1200) : 'pager not found'; }"""

JS_PAGE_SIZE = """() => {
  for (const s of document.querySelectorAll('select')) {
    const opts = [...s.options].map(o => parseInt(o.value, 10)).filter(v => v >= 10 && v <= 100);
    if (opts.length >= 2) { const best = Math.max(...opts); s.value = String(best); s.dispatchEvent(new Event('change', {bubbles: true})); return best; }
  }
  return 0;
}"""


def _lines(cell):
    return [re.sub(r"\s+", " ", l).strip(" ,") for l in str(cell or "").splitlines() if l.strip(" ,\t")]


def _col(headers, *keys, default=None):
    for i, h in enumerate(headers):
        hl = h.lower()
        if all(k in hl for k in keys):
            return i
    return default


def parse_rows(headers, rows):
    """headers: list[str]; rows: list[{'cells': [...], 'href': str|None}] -> raw dicts."""
    if any(len(h) > 200 for h in headers):      # wrong (layout) table captured: use the known column order
        headers = []
    c_id = _col(headers, "tender/proposal", default=_col(headers, "id", default=1))
    c_title = _col(headers, "title", default=2)
    c_org = _col(headers, "ministry", default=_col(headers, "organization", default=3))
    c_meth = _col(headers, "method", default=4)
    c_date = _col(headers, "closing", default=_col(headers, "publishing", default=5))
    out = []
    for r in rows:
        cells = r["cells"]
        def get(i):
            return cells[i] if i is not None and i < len(cells) else ""
        id_lines = _lines(get(c_id))
        tid = next((m.group(0) for l in id_lines for m in [re.fullmatch(r"\d{5,}", l)] if m), None)
        if not tid and r.get("href"):
            m = re.search(r"[?&]id=(\d{4,})", r["href"])
            tid = m.group(1) if m else None
        if not tid:
            continue
        ref = next((l for l in id_lines if l != tid and not STATUS_WORDS.match(l)), None)
        t_lines = _lines(get(c_title))
        nature = normalize.norm_nature(t_lines[0]) if t_lines else None
        title = " ".join(t_lines[1:] if nature and len(t_lines) > 1 else t_lines).strip()
        if len(title) < 4:
            continue
        o_lines = _lines(get(c_org))
        ministry = o_lines[0] if o_lines else None
        org = o_lines[-1] if o_lines else None
        meth_text = get(c_meth)
        d_text = get(c_date)
        dates = normalize.find_dates(d_text)
        published = dates[0][1].isoformat() if dates else None
        deadline = dates[-1][1].isoformat() if len(dates) > 1 else None
        times = TIME_RX.findall(d_text)
        raw = {
            "title": title[:300], "organization": org, "ministry": ministry, "ref_no": ref,
            "nature": nature, "method": normalize.find_method(meth_text),
            "proc_type": "ICT" if re.search(r"\bICT\b", meth_text) else ("NCT" if re.search(r"\bNCT\b", meth_text) else None),
            "published": published, "deadline": deadline,
            "deadline_time": times[-1].upper() if len(times) > 1 else None,
            "link": DETAIL.format(id=tid), "summary": "", "_id": tid, "no_ai": True,
        }
        out.append(raw)
    return out


def _row_id(r):
    m = re.search(r"\b(\d{5,})\b", (r["cells"][1] if len(r["cells"]) > 1 else ""))
    return "egp-" + m.group(1) if m else None


def _write_debug(lines):
    try:
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_FILE.write_text("\n".join(lines)[:20000], encoding="utf-8")
    except OSError:
        pass


def scrape(url=DEFAULT_URL, max_pages=40, delay=1.5, page_timeout=60000, log=print, known_ids=None):
    """Drive the browser; return (headers, rows, debug_lines)."""
    from .browser import LAUNCH_ARGS, _sync
    from . import net
    dbg, requests_seen = [f"url: {url}"], []
    sync_playwright = _sync()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            page = browser.new_page(user_agent=net.UA, locale="en-US")
            page.on("request", lambda r: requests_seen.append(f"{r.method} {r.url}")
                    if r.resource_type in ("xhr", "fetch", "document") else None)
            page.goto(url, wait_until="domcontentloaded", timeout=page_timeout)
            dbg.append("final url: " + page.url)
            dbg.append("title: " + (page.title() or ""))
            data = None
            for attempt in range(3):
                try:
                    page.wait_for_function(
                        "() => document.querySelectorAll('table tr td').length > 12", timeout=25000)
                except Exception:
                    pass
                data = page.evaluate(JS_TABLE)
                if data and data["rows"]:
                    break
                if attempt == 0:   # some versions need the Search button pressed once
                    try:
                        page.locator("input[value*='Search' i], button:has-text('Search')").first.click(timeout=3000)
                    except Exception:
                        pass
                page.wait_for_timeout(4000)
            if not data or not data["rows"]:
                dbg.append("NO TABLE ROWS FOUND")
                try:
                    dbg.append("page text:\n" + page.inner_text("body")[:3500])
                except Exception:
                    pass
                dbg.append("requests:\n" + "\n".join(requests_seen[-40:]))
                return (data or {}).get("headers", []), [], dbg
            try:
                dbg.append("form controls:\n" + "\n".join(page.evaluate(JS_FORM_DUMP)))
                dbg.append("pager html: " + str(page.evaluate(JS_PAGER_HTML)))
            except Exception as e:
                dbg.append(f"form dump failed: {e}")
            headers, all_rows, seen_first = data["headers"], list(data["rows"]), {data["rows"][0]["cells"][1] if len(data["rows"][0]["cells"]) > 1 else ""}
            try:
                size = page.evaluate(JS_PAGE_SIZE)
                if size:
                    page.wait_for_timeout(3500)
                    data2 = page.evaluate(JS_TABLE)
                    if data2 and len(data2["rows"]) >= len(data["rows"]):
                        all_rows = list(data2["rows"])
                        seen_first = {data2["rows"][0]["cells"][1] if len(data2["rows"][0]["cells"]) > 1 else ""}
                dbg.append(f"page size set to: {size}")
            except Exception as e:
                dbg.append(f"page size not changed: {e}")
            for n in range(1, max_pages):
                time.sleep(delay)
                try:
                    clicked = page.evaluate(JS_NEXT)
                except Exception:
                    clicked = False
                if not clicked:
                    dbg.append(f"no Next control after page {n}")
                    break
                new = None
                for _ in range(24):
                    page.wait_for_timeout(750)
                    cur = page.evaluate(JS_TABLE)
                    if cur and cur["rows"]:
                        first = cur["rows"][0]["cells"][1] if len(cur["rows"][0]["cells"]) > 1 else ""
                        if first not in seen_first:
                            new = cur
                            seen_first.add(first)
                            break
                if not new:
                    dbg.append(f"page {n + 1} did not change; stopping")
                    try:
                        dbg.append("page number text: " + str(page.evaluate(JS_PAGE_NO)))
                        dbg.append("pager html after click: " + str(page.evaluate(JS_PAGER_HTML)))
                    except Exception:
                        pass
                    break
                all_rows.extend(new["rows"])
                if known_ids and all(_row_id(r) in known_ids for r in new["rows"]):
                    dbg.append(f"page {n + 1} fully known; stopping (incremental)")
                    break
            dbg.append("headers: " + json.dumps(headers, ensure_ascii=False))
            dbg.append("first rows: " + json.dumps(all_rows[:2], ensure_ascii=False))
            dbg.append("requests:\n" + "\n".join(requests_seen[-25:]))
            return headers, all_rows, dbg
        finally:
            browser.close()


def run_source(src, now, scraper=scrape, log=print, existing=None):
    known = {r["id"] for r in (existing or []) if r.get("source_id") == src["id"]}
    try:
        headers, rows, dbg = scraper(src.get("url") or DEFAULT_URL, int(src.get("pages", 40)),
                                     float(src.get("delay", 1.5)), known_ids=known)
    except TypeError:      # simple scrapers (tests) without the incremental argument
        headers, rows, dbg = scraper(src.get("url") or DEFAULT_URL, int(src.get("pages", 40)),
                                     float(src.get("delay", 1.5)))
    _write_debug(dbg)
    parsed = parse_rows(headers, rows)
    if not parsed:
        raise RuntimeError(
            "e-GP list could not be read" + (" (no rows found)" if not rows else " (rows did not match the expected columns)")
            + "; see data/egp_debug.txt in the repository")
    records, seen = [], set()
    for raw in parsed:
        if raw["_id"] in seen:
            continue
        seen.add(raw["_id"])
        rec = normalize.build_record(src, raw, now)
        rec["id"] = "egp-" + raw["_id"]
        rec["via"] = "egp"
        records.append(rec)
    return records
