"""Normalization helpers: dates, categories, IDs, de-duplication, merging."""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BD = ZoneInfo("Asia/Dhaka")

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Bangla digits -> ASCII so date regexes work on Bangla text too.
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

DATE_PATTERNS = [
    # 2026-10-24
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    # 24/10/2026, 24-10-2026, 24.10.2026
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy"),
    # 24-Oct-2026, 24 October 2026, 24 Oct, 2026
    (re.compile(r"\b(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})\b"), "dMy"),
]

DEADLINE_LABEL = re.compile(
    r"(closing|deadline|last\s*date|due|submission|on\s+or\s+before|no\s+later\s+than|"
    r"not\s+later\s+than|(?:submitted|received|delivered|sent)\s+(?:by|on|before)|"
    r"must\s+be\s+(?:delivered|received|submitted)|বন্ধ|শেষ\s*তারিখ|জমা)", re.I)


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def find_dates(text):
    """Return [(position, date)] for every date found in text."""
    text = (text or "").translate(_BN_DIGITS)
    found = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            if kind == "ymd":
                d = _mk(m.group(1), m.group(2), m.group(3))
            elif kind == "dmy":
                d = _mk(m.group(3), m.group(2), m.group(1))
            else:
                mon = MONTHS.get(m.group(2)[:3].lower())
                d = _mk(m.group(3), mon, m.group(1)) if mon else None
            if d and 2000 <= d.year <= 2100:
                found.append((m.start(), d))
    return sorted(found)


def find_deadline(text):
    """Best-effort closing date. Prefers a date next to a deadline-style label,
    otherwise the latest date if several appear (publish date < closing date)."""
    dates = find_dates(text)
    if not dates:
        return None
    t = (text or "").translate(_BN_DIGITS)
    for lm in DEADLINE_LABEL.finditer(t):
        after = [d for pos, d in dates if 0 <= pos - lm.end() <= 60]
        if after:
            return after[0].isoformat()
    if len(dates) >= 2:
        return max(d for _, d in dates).isoformat()
    return None


ORG_RX = re.compile(
    r"(?:organi[sz]ation|procuring\s*entity|ministry|division|agency|পিই|প্রতিষ্ঠান)"
    r"\s*[:\-]\s*([^|\n;<]{3,120})", re.I)


def find_org(text):
    m = ORG_RX.search(text or "")
    return m.group(1).strip(" ,.-") if m else None


CATEGORY_RULES = [
    ("Civil works", r"\b(road|bridge|culvert|building|construction|embankment|drain|"
                    r"pavement|repair|renovation|earthwork|civil|works?)\b|সড়ক|রাস্তা|সেতু|নির্মাণ|মেরামত|ভবন|বাঁধ"),
    ("ICT", r"\b(software|hardware|server|network|ict|computer|laptop|website|digital|"
            r"cctv|it\s+equipment|database|cloud)\b|সফটওয়্যার|কম্পিউটার|ডিজিটাল"),
    ("Furniture", r"\b(furniture|desk|chair|table|cabinet|almirah|bookshelf|interior)\b|আসবাব|চেয়ার|টেবিল"),
    ("Medical", r"\b(medical|medicine|hospital|surgical|pharma|diagnostic|reagent|vaccine)\b|ঔষধ|চিকিৎসা|হাসপাতাল"),
    ("Consultancy", r"\b(consult\w*|survey|study|eoi|expression\s+of\s+interest|rfp|design\s+and\s+supervision)\b|পরামর্শক"),
    ("Electrical", r"\b(electric\w*|transformer|solar|generator|substation|cable|lighting)\b|বিদ্যুৎ|সোলার"),
    ("Vehicles", r"\b(vehicle|car|jeep|microbus|motorcycle|bus|truck|ambulance)\b|যানবাহন|গাড়ি"),
    ("Goods", r"\b(supply|procurement\s+of|purchase|goods|stationery|equipment|materials?)\b|সরবরাহ|ক্রয়"),
]
_CATEGORY_RX = [(n, re.compile(p, re.I)) for n, p in CATEGORY_RULES]


def guess_category(text):
    for name, rx in _CATEGORY_RX:
        if rx.search(text or ""):
            return name
    return "Other"


def norm_text(s):
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


EGP_ID_RX = re.compile(r"(?:[?&](?:id|tenderid|tenderId)=|/tender/?)(\d{4,})", re.I)


def make_id(source_id, title, link):
    m = EGP_ID_RX.search(link or "")
    if m and source_id.startswith("egp"):
        return "egp-" + m.group(1)
    raw = f"{source_id}|{norm_text(title)}|{link}"
    return source_id + "-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def dedupe_key(rec):
    raw = "|".join([norm_text(rec.get("title"))[:140],
                    norm_text(rec.get("organization")),
                    rec.get("deadline") or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_record(source, raw, now):
    """Turn a raw parsed item into a tender record."""
    title = (raw.get("title") or "").strip()
    summary = (raw.get("summary") or "").strip()
    blob = f"{title}\n{summary}"
    rec = {
        "id": make_id(source["id"], title, raw.get("link")),
        "title": title,
        "organization": raw.get("organization") or find_org(summary),
        "category": guess_category(blob),
        "deadline": raw.get("deadline") or find_deadline(summary),
        "published": raw.get("published"),
        "summary": summary[:400],
        "link": raw.get("link"),
        "source_id": source["id"],
        "source": source["name"],
        "kind": source.get("kind", "public"),
        "first_seen": now.isoformat(timespec="seconds"),
        "last_seen": now.isoformat(timespec="seconds"),
        "also_at": [],
    }
    rec["needs_ai"] = not (rec["deadline"] and rec["organization"])
    return rec


def merge(existing, fresh, now):
    """Merge fresh records into existing ones. Keeps first_seen, fills gaps,
    and folds cross-source duplicates (same title+org+deadline) into one."""
    by_id = {r["id"]: r for r in existing}
    by_key = {dedupe_key(r): r for r in existing}
    for rec in fresh:
        cur = by_id.get(rec["id"])
        if cur:
            for f in ("organization", "deadline", "published", "summary"):
                if not cur.get(f) and rec.get(f):
                    cur[f] = rec[f]
            cur["last_seen"] = rec["last_seen"]
            cur["needs_ai"] = cur.get("needs_ai", False) and not (cur.get("deadline") and cur.get("organization"))
            continue
        twin = by_key.get(dedupe_key(rec))
        if twin and twin["source_id"] != rec["source_id"]:
            if rec["link"] and rec["link"] != twin["link"] and rec["link"] not in twin["also_at"]:
                twin["also_at"].append(rec["link"])
            twin["last_seen"] = rec["last_seen"]
            continue
        by_id[rec["id"]] = rec
        by_key[dedupe_key(rec)] = rec
    return list(by_id.values())


def prune(records, now, closed_days=30, undated_days=60):
    today = now.date()
    keep = []
    for r in records:
        if r.get("deadline"):
            try:
                if date.fromisoformat(r["deadline"]) < today - timedelta(days=closed_days):
                    continue
            except ValueError:
                pass
        else:
            try:
                fs = datetime.fromisoformat(r["first_seen"])
                if fs.tzinfo is None:
                    fs = fs.replace(tzinfo=timezone.utc)
                if fs < now - timedelta(days=undated_days):
                    continue
            except (ValueError, KeyError):
                pass
        keep.append(r)
    return keep
