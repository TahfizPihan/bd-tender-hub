import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import normalize, parsers  # noqa: E402

HERE = Path(__file__).parent
NOW = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)
SRC = {"id": "egp-daily", "name": "e-GP (daily RSS)", "kind": "public"}


def records():
    raw = parsers.parse_rss((HERE / "sample_rss.xml").read_text(encoding="utf-8"))
    return [normalize.build_record(SRC, r, NOW) for r in raw]


def test_rss_parses_all_items():
    assert len(records()) == 4


def test_ids_come_from_egp_tender_id():
    ids = [r["id"] for r in records()]
    assert ids == ["egp-900001", "egp-900002", "egp-900003", "egp-900004"]


def test_deadline_and_org_extraction():
    r = {x["id"]: x for x in records()}
    assert r["egp-900001"]["deadline"] == "2026-11-05"   # label wins over publish date
    assert r["egp-900001"]["organization"] == "Roads and Highways Department"
    assert r["egp-900002"]["deadline"] == "2026-11-02"
    assert r["egp-900003"]["deadline"] == "2026-11-12"   # latest of two dates
    assert r["egp-900004"]["deadline"] == "2026-11-10"   # Bangla digits


def test_categories():
    r = {x["id"]: x for x in records()}
    assert r["egp-900001"]["category"] == "Civil works"
    assert r["egp-900002"]["category"] == "Furniture"
    assert r["egp-900003"]["category"] == "ICT"
    assert r["egp-900004"]["category"] == "Civil works"  # Bangla keywords


def test_needs_ai_flag():
    r = {x["id"]: x for x in records()}
    assert r["egp-900001"]["needs_ai"] is False
    assert r["egp-900003"]["needs_ai"] is True  # no organization found


def test_html_links_heuristic():
    items = parsers.parse_html_links((HERE / "sample_page.html").read_text(encoding="utf-8"),
                                     "https://agency.example.gov.bd/notices/")
    links = [i["link"] for i in items]
    assert "https://agency.example.gov.bd/files/tender-notice-77.pdf" in links
    assert "https://agency.example.gov.bd/notice/78" in links
    assert len(links) == 2                      # nav + about + duplicate dropped
    sol = [i for i in items if "Solar" in i["title"]][0]
    assert normalize.find_deadline(sol["summary"]) == "2026-11-09"


def test_merge_is_idempotent_and_keeps_first_seen():
    first = normalize.merge([], records(), NOW)
    later = datetime(2026, 10, 25, tzinfo=timezone.utc)
    again = [normalize.build_record(SRC, p, later)
             for p in parsers.parse_rss((HERE / "sample_rss.xml").read_text(encoding="utf-8"))]
    second = normalize.merge(first, again, later)
    assert len(second) == 4
    assert all(r["first_seen"].startswith("2026-10-24") for r in second)
    assert all(r["last_seen"].startswith("2026-10-25") for r in second)


def test_cross_source_duplicate_is_folded():
    first = normalize.merge([], records(), NOW)
    twin_src = {"id": "lged", "name": "LGED", "kind": "public"}
    dup = normalize.build_record(twin_src, {
        "title": "Construction of Upazila Health Complex Road, Package RHD-12",
        "link": "https://lged.example/notice/1",
        "summary": "Organization: Roads and Highways Department; Closing Date: 05-Nov-2026"}, NOW)
    merged = normalize.merge(first, [dup], NOW)
    assert len(merged) == 4
    hit = [r for r in merged if r["id"] == "egp-900001"][0]
    assert hit["also_at"] == ["https://lged.example/notice/1"]


def test_prune_drops_long_closed():
    recs = normalize.merge([], records(), NOW)
    recs[0]["deadline"] = "2026-08-01"
    kept = normalize.prune(recs, NOW)
    assert len(kept) == 3


def test_output_is_json_serializable():
    json.dumps(records(), ensure_ascii=False)
