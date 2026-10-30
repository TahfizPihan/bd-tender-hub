import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import bppa, normalize  # noqa: E402

HERE = Path(__file__).parent
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
rd = lambda n: (HERE / n).read_text(encoding="utf-8")


def test_list_rows():
    rows = bppa.parse_list(rd("sample_bppa_list.html"), "goods")
    assert [r["detail_id"] for r in rows] == ["98698", "98699", "98685", "98695"]
    r = rows[0]
    assert r["title"] == "Anti Drone System" and r["ref_no"] == "44.02.1205.005.01.412.46"
    assert r["entity"] == "DDG, Communication Branch" and r["district"] == "Dhaka"
    assert (r["published"], r["deadline"], r["deadline_time"]) == ("2026-10-19", "2026-11-02", "08:00 PM")
    assert r["link"] == "https://www.bppa.gov.bd/advertisement-goods/details-98698.html"
    assert rows[1]["ref_no"] == "44.03.0000.017.07.229.2026-3659"
    assert rows[3]["ref_no"] == "27.12.6704.570.01.022.26.1843"        # stray space removed


def test_detail_two_column_layout():
    f = bppa.detail_fields(bppa.parse_detail(rd("sample_bppa_detail_a.html")), "Goods")
    assert f["organization"] == "Pragoti Industries Limited"
    assert f["ministry"] == "Ministry of Industries"
    assert f["method"] == "LTM" and f["proc_type"] == "NCT"
    assert f["funding"] == "Own Funds" and "partner" not in f
    assert f["deadline"] == "2026-02-10" and f["deadline_time"] == "12:00 PM"
    assert f["published"] == "2026-01-28" and f["ref_no"] == "36.93.0000.518.07.19.25.128"
    assert f["summary_text"] == "Various types of stationary items" and f["doc_price"] == "500"


def test_detail_four_column_layout_with_partner():
    f = bppa.detail_fields(bppa.parse_detail(rd("sample_bppa_detail_b.html")), "Works")
    assert f["method"] == "OTM" and f["partner"] == "ADB" and f["nature"] == "Works"
    assert f["organization"] == "Executive Engineer, LGED, Rangpur" and f["district"] == "Rangpur"
    assert f["deadline"] == "2026-11-12" and f["deadline_time"] == "11:30 AM"
    assert "culverts" in f["summary_text"]


def fake_fetcher(calls):
    def f(url):
        calls.append(url)
        if "details-98698" in url:
            return rd("sample_bppa_detail_b.html")
        if "details-" in url:
            return rd("sample_bppa_detail_a.html")
        if "advertisement-goods.html" in url and "page=0" in url:
            return rd("sample_bppa_list.html")
        return "<html><body><table></table></body></html>"   # empty page
    return f


SRC = {"id": "bppa-govt", "name": "BPPA", "type": "bppa", "kind": "public",
       "categories": ["goods"], "pages": 3, "detail_per_run": 3, "delay": 0}


def test_run_source_collects_and_enriches():
    calls = []
    recs = bppa.run_source(SRC, NOW, existing=[], fetcher=fake_fetcher(calls), sleep=lambda s: None, log=lambda *a: None)
    assert len(recs) == 4
    r = {x["id"]: x for x in recs}["bppa-goods-98698"]
    assert r["method"] == "OTM" and r["partner"] == "ADB" and r["kind"] == "public" and r["via"] == "bppa"
    assert r["deadline"] == "2026-11-12" and r["detail_done"] is True and r["needs_ai"] is False
    assert r["category"] == "Civil works"
    detail_calls = [c for c in calls if "details-" in c]
    assert len(detail_calls) == 3                       # capped per run
    done = [x for x in recs if x.get("detail_done")]
    assert len(done) == 3 and sum(1 for x in recs if not x.get("detail_done")) == 1


def test_second_run_adds_nothing_new_but_finishes_details():
    calls = []
    first = bppa.run_source(SRC, NOW, existing=[], fetcher=fake_fetcher(calls), sleep=lambda s: None, log=lambda *a: None)
    existing = normalize.merge([], first, NOW)
    calls.clear()
    again = bppa.run_source(SRC, NOW, existing=existing, fetcher=fake_fetcher(calls), sleep=lambda s: None, log=lambda *a: None)
    assert again == []                                   # nothing new
    assert sum(1 for c in calls if "details-" in c) == 1  # the one record still missing details
    assert all(x.get("detail_done") for x in existing)   # enriched in place


def test_site_unreachable_raises():
    def boom(url):
        raise OSError("blocked")
    with pytest.raises(RuntimeError):
        bppa.run_source(SRC, NOW, existing=[], fetcher=boom, sleep=lambda s: None, log=lambda *a: None)


def test_cross_source_duplicate_by_reference_number():
    calls = []
    recs = bppa.run_source(SRC, NOW, existing=[], fetcher=fake_fetcher(calls), sleep=lambda s: None, log=lambda *a: None)
    base = normalize.merge([], recs, NOW)
    egp = normalize.build_record({"id": "egp-list", "name": "e-GP", "kind": "public"},
                                 {"title": "Totally different wording of the same tender", "organization": "X",
                                  "ref_no": "36.93.0000.518.07.19.25.128", "link": "https://www.eprocure.gov.bd/resources/common/ViewTender.jsp?id=1177000&h=t"}, NOW)
    egp["id"] = "egp-1177000"
    merged = normalize.merge(base, [egp], NOW)
    assert len(merged) == 4
    assert egp["link"] in [r for x in merged for r in x["also_at"]]


def test_plain_text_fallback_layout():
    html = "<html><body><p>Procurement Method</p><p>:</p><p>NCT Open Tendering Method (OTM)</p><p>Development Partner</p><p>JICA</p></body></html>"
    f = bppa.detail_fields(bppa.parse_detail(html), "Works")
    assert f["method"] == "OTM" and f["partner"] == "JICA"
