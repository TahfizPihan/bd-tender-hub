"""World Bank procurement notices for Bangladesh (public JSON API, no key needed).

Only open-opportunity notice types are collected (contract awards are skipped). The API's
`submission_date` field equals the notice date in practice, so it is NOT used as the bid
deadline; the deadline is read from the notice text when it is stated there.
"""
import re

import requests

from . import net, normalize, parsers

API = "https://search.worldbank.org/api/v2/procnotices"
DETAIL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/"
DEFAULT_TYPES = ["Invitation for Bids", "Request for Expression of Interest",
                 "Invitation for Prequalification"]


def parse_notices(data):
    out = []
    for n in (data or {}).get("procnotices", []) or []:
        nid = n.get("id")
        title = re.sub(r"\s+", " ", str(n.get("bid_description") or n.get("project_name") or "")).strip()
        if not nid or len(title) < 6:
            continue
        text = parsers._strip_html(n.get("notice_text") or "")
        bits = [n.get("notice_type"), n.get("procurement_method_name"),
                ("Ref " + n["bid_reference_no"]) if n.get("bid_reference_no") else None]
        pub = normalize.find_dates(str(n.get("noticedate") or ""))
        out.append({
            "title": title[:300],
            "organization": (n.get("project_name") or "").strip().strip('"') or None,
            "summary": " · ".join(b for b in bits if b),
            "published": pub[0][1].isoformat() if pub else None,
            "deadline": normalize.find_deadline(text),
            "link": DETAIL + str(nid),
            "_id": str(nid),
        })
    return out


def run_source(src, now, getter=None, log=print):
    types = src.get("notice_types") or DEFAULT_TYPES
    rows = int(src.get("rows", 100))
    records = []
    for t in types:
        params = {"format": "json", "project_ctry_name_exact": src.get("country", "Bangladesh"),
                  "notice_type_exact": t, "rows": rows, "srt": "noticedate", "order": "desc"}
        if getter:
            data = getter(params)
        else:
            r = requests.get(API, params=params, headers=net.HEADERS, timeout=45)
            r.raise_for_status()
            data = r.json()
        for raw in parse_notices(data):
            rec = normalize.build_record(src, raw, now)
            rec["id"] = "wb-" + raw["_id"]
            rec["via"] = "worldbank"
            records.append(rec)
    return records
