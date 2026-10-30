"""BPPA (Bangladesh Public Procurement Authority) tender advertisements.

Public, login-free, server-rendered pages:
  list:   https://www.bppa.gov.bd/advertisement-notices/advertisement-{goods|works|services|physical-service}.html?page=N
  detail: https://www.bppa.gov.bd/advertisement-{category}/details-{ID}.html

The list gives title, reference no., procuring entity, issue date, closing date/time and place.
The detail page adds ministry, agency, procurement method (OTM, LTM ...), funding source /
development partner, document price and a description. Detail pages are fetched only for
tenders that have none yet, a limited number per run, with a pause between requests.
"""
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import net, normalize

BASE = "https://www.bppa.gov.bd"
LIST_URL = BASE + "/advertisement-notices/advertisement-{cat}.html"
CATEGORIES = {"goods": "Goods", "works": "Works", "services": "Services", "physical-service": "Physical service"}

DETAIL_HREF = re.compile(r"/advertisement-([a-z\-]+)/details-(\d+)\.html", re.I)
DATE_TIME = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}\s*[AP]M))?", re.I)
REF_RX = re.compile(r"\b\d{2}\.\d{2}\b(?:\s?\.\s?\d{1,6}){3,}(?:[\-/]\d+)?")

LABELS = [
    "ministry/division", "ministry", "agency", "procuring entity name", "procuring entity code",
    "procuring entity district", "invitation for", "invitation reference no", "date", "procurement method",
    "budget and source of funds", "development partner", "project/programme code", "project/programme name",
    "tender package no", "tender package name", "tender publication date", "tender last selling date",
    "tender closing date and time", "tender opening date and time", "office address information",
    "selling tender document (principal)", "receiving tender document", "opening tender document",
    "selling tender document (others)", "place/date/time of tender meeting (optional)",
    "eligibility of tenderer", "brief description of goods or works", "brief description of related services",
    "tender document price", "tender lot information", "name of official inviting tender", "designation",
    "address", "contact", "contact information",
]
_LABEL_SET = set(LABELS)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


# ---------------------------------------------------------------- list page
def parse_list(html, category, base=BASE):
    """Return raw rows from one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = DETAIL_HREF.search(a["href"])
        if not m:
            continue
        did = m.group(2)
        if did in seen:
            continue
        seen.add(did)
        tr = a.find_parent("tr")
        if tr is None:
            continue
        cells = [_clean(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
        title_cell_idx = next((i for i, td in enumerate(tr.find_all(["td", "th"])) if a in td.find_all("a")), 1)
        title = _clean(a.get_text(" "))
        cell_txt = cells[title_cell_idx] if title_cell_idx < len(cells) else title
        ref = None
        mref = REF_RX.search(cell_txt.replace(title, " ")) or REF_RX.search(cell_txt)
        if mref:
            ref = re.sub(r"\s+", "", mref.group(0)).strip(".-/ ")
        entity = cells[title_cell_idx + 1] if title_cell_idx + 1 < len(cells) else None
        place = cells[-1] if len(cells) > title_cell_idx + 4 else None
        dates = DATE_TIME.findall(" ".join(cells[title_cell_idx + 1:]))
        issue = _dmy(dates[0][0]) if dates else None
        close = _dmy(dates[1][0]) if len(dates) > 1 else None
        ctime = dates[1][1].upper() if len(dates) > 1 and dates[1][1] else None
        if not title:
            continue
        rows.append({"detail_id": did, "category": m.group(1).lower(), "title": title, "ref_no": ref,
                     "entity": entity, "published": issue, "deadline": close, "deadline_time": ctime,
                     "district": place,
                     "link": urljoin(base + "/", a["href"])})
    return rows


def _dmy(s):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", (s or "").strip())
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        from datetime import date
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


# -------------------------------------------------------------- detail page
def parse_detail(html):
    """Label/value pairs from a detail page.

    Reads table rows first (2-column and 4-column layouts: label, value, label, value) so a value
    that happens to equal a label name (e.g. 'Development Partner' as the funding source) is not
    mistaken for a label. Falls back to scanning the page text line by line."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    out = {}
    for tr in soup.find_all("tr"):
        cells = [_clean(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c != ":"]
        i = 0
        while i < len(cells):
            key = cells[i].rstrip(":").strip().lower()
            if key in _LABEL_SET:
                val = cells[i + 1].lstrip(":").strip() if i + 1 < len(cells) else ""
                if key not in out:
                    out[key] = val
                i += 2
            else:
                i += 1
    if out:
        return out
    lines = [l.strip() for l in soup.get_text("\n").splitlines()]
    lines = [l for l in lines if l and l != ":"]
    i = 0
    while i < len(lines):
        key = lines[i].rstrip(":").strip().lower()
        if key in _LABEL_SET and key not in out:
            val = ""
            if i + 1 < len(lines) and lines[i + 1].rstrip(":").strip().lower() not in _LABEL_SET:
                val = lines[i + 1].lstrip(":").strip()
                i += 1
            out[key] = val
        i += 1
    return out


def detail_fields(d, category_name):
    method_raw = d.get("procurement method", "")
    funds = d.get("budget and source of funds", "")
    partner_raw = d.get("development partner", "")
    entity = d.get("procuring entity name") or ""
    agency = d.get("agency") or ""
    ministry = d.get("ministry/division") or d.get("ministry") or ""
    desc = d.get("brief description of goods or works") or ""
    rel = d.get("brief description of related services") or ""
    closing = d.get("tender closing date and time", "")
    mdt = DATE_TIME.search(closing)
    out = {
        "organization": entity or agency or None,
        "ministry": ministry or None,
        "method": normalize.find_method(method_raw),
        "proc_type": "ICT" if re.search(r"\bICT\b", method_raw) else ("NCT" if re.search(r"\bNCT\b", method_raw) else None),
        "funding": (partner_raw or funds or None),
        "partner": normalize.find_partner(partner_raw, d.get("project/programme name"), funds),
        "nature": normalize.norm_nature(d.get("invitation for")) or category_name,
        "doc_price": d.get("tender document price") or None,
        "district": d.get("procuring entity district") or None,
        "ref_no": (d.get("invitation reference no") or "").replace(" ", "") or None,
        "summary_text": _clean(" ".join(x for x in (desc, rel) if x)),
    }
    if mdt:
        out["deadline"] = _dmy(mdt.group(1))
        out["deadline_time"] = mdt.group(2).upper() if mdt.group(2) else None
    pub = DATE_TIME.search(d.get("tender publication date", ""))
    if pub:
        out["published"] = _dmy(pub.group(1))
    return {k: v for k, v in out.items() if v}


# ------------------------------------------------------------------- source
def run_source(src, now, existing=None, fetcher=None, sleep=time.sleep, log=print):
    """Collect list pages for every category, then enrich new rows from their detail pages."""
    fetcher = fetcher or net.fetch
    cats = src.get("categories") or list(CATEGORIES)
    pages = int(src.get("pages", 6))
    detail_cap = int(src.get("detail_per_run", 60))
    delay = float(src.get("delay", 1.2))
    known = {r["id"]: r for r in (existing or []) if r.get("source_id") == src["id"]}
    records, failures, total_pages = {}, 0, 0
    for cat in cats:
        cat_name = CATEGORIES.get(cat, cat.title())
        for page in range(pages):
            url = f"{LIST_URL.format(cat=cat)}?ministryId.id=&agencyId.id=&procurementMethodId.id=&page={page}"
            try:
                html = fetcher(url)
            except Exception as e:
                log(f"  [bppa] {cat} page {page}: {e}")
                failures += 1
                break
            total_pages += 1
            rows = parse_list(html, cat)
            if not rows:
                if page == 0:
                    failures += 1
                    log(f"  [bppa] {cat}: no rows found on first page")
                break
            new_here = 0
            for r in rows:
                rid = f"bppa-{r['category']}-{r['detail_id']}"
                if rid in known:
                    continue
                new_here += 1
                raw = {"title": r["title"], "organization": r["entity"], "published": r["published"],
                       "deadline": r["deadline"], "deadline_time": r["deadline_time"], "link": r["link"],
                       "ref_no": r["ref_no"], "district": r["district"], "nature": cat_name, "no_ai": True,
                       "summary": ""}
                rec = normalize.build_record(src, raw, now)
                rec["id"] = rid
                rec["via"] = "bppa"
                records[rid] = rec
            # incremental runs: once a whole page is already known, older pages are known too
            if new_here == 0 and page >= 1 and known:
                break
            sleep(delay)
    if total_pages == 0:
        raise RuntimeError("BPPA site could not be read")

    # enrich: new records plus older ones still missing details, newest first
    todo = [r for r in list(records.values()) + [k for k in known.values() if not k.get("method") and not k.get("detail_done")]
            if not r.get("detail_done")]
    todo.sort(key=lambda r: r.get("published") or "", reverse=True)
    done = 0
    for rec in todo[:detail_cap]:
        try:
            html = fetcher(rec["link"])
        except Exception as e:
            log(f"  [bppa] detail {rec['id']}: {e}")
            sleep(delay)
            continue
        f = detail_fields(parse_detail(html), rec.get("nature"))
        desc = f.pop("summary_text", "")
        rec.update(f)                      # the detail page is the authority
        if desc:
            rec["summary"] = desc[:400]
            cat = normalize.guess_category(rec["title"] + " " + desc)
            rec["category"] = cat if cat != "Other" else {"Works": "Civil works", "Goods": "Goods"}.get(rec.get("nature"), "Other")
        rec["detail_done"] = True
        rec["needs_ai"] = False
        done += 1
        sleep(delay)
    log(f"  [bppa] {total_pages} list page(s), {len(records)} new, {done} detail page(s) read")
    return list(records.values())
