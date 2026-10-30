import functools
import http.server
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import egp_browser, normalize  # noqa: E402

HERE = Path(__file__).parent
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SRC = {"id": "egp-list", "name": "e-GP eTenders list (Govt)", "kind": "public", "type": "egp_browser"}

HEADERS = ["S. No.", "Tender/Proposal ID, Reference No, Public Status", "Procurement Nature, Title",
           "Ministry, Division, Organization, PE", "Type, Method", "Publishing Date and Time, Closing Date and Time"]
ROW = {"cells": ["1", "1177005\nMOWR/BWDB/2026/105\nLive", "Works\nConstruction of embankment, Package 6",
                 "Ministry of Water Resources,\nWater Resources Division,\nBangladesh Water Development Board,\nXEN, Rangpur O&M Division",
                 "NCT\nOTM", "20-Oct-2026 10:00\n15-Nov-2026 12:00"], "href": "/resources/common/ViewTender.jsp?id=1177005&h=t"}


def test_parse_rows():
    out = egp_browser.parse_rows(HEADERS, [ROW])
    assert len(out) == 1
    r = out[0]
    assert r["_id"] == "1177005" and r["ref_no"] == "MOWR/BWDB/2026/105"
    assert r["nature"] == "Works" and r["title"] == "Construction of embankment, Package 6"
    assert r["ministry"] == "Ministry of Water Resources" and r["organization"] == "XEN, Rangpur O&M Division"
    assert r["method"] == "OTM" and r["proc_type"] == "NCT"
    assert (r["published"], r["deadline"], r["deadline_time"]) == ("2026-10-20", "2026-11-15", "12:00")
    assert r["link"].endswith("ViewTender.jsp?id=1177005&h=t")


def test_rows_without_an_id_or_title_are_skipped():
    bad = {"cells": ["2", "Live", "Works\nx", "A", "B", "C"], "href": None}
    assert egp_browser.parse_rows(HEADERS, [bad]) == []


def test_run_source_builds_records_and_dedupes():
    scr = lambda url, pages, delay: (HEADERS, [ROW, ROW], ["dbg"])
    recs = egp_browser.run_source(SRC, NOW, scraper=scr)
    assert [r["id"] for r in recs] == ["egp-1177005"]
    r = recs[0]
    assert r["via"] == "egp" and r["kind"] == "public" and r["method"] == "OTM" and r["needs_ai"] is False
    assert r["category"] == "Civil works"          # from the nature 'Works' / title


def test_run_source_reports_unreadable_list(tmp_path, monkeypatch):
    monkeypatch.setattr(egp_browser, "DEBUG_FILE", tmp_path / "dbg.txt")
    with pytest.raises(RuntimeError, match="egp_debug"):
        egp_browser.run_source(SRC, NOW, scraper=lambda u, p, d: ([], [], ["NO TABLE ROWS FOUND"]))
    assert "NO TABLE ROWS" in (tmp_path / "dbg.txt").read_text()


# ---- real browser against a local page that builds its table with JavaScript -----------------
def _browser_ok():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(args=["--no-sandbox"]).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_ok(), reason="Chromium/Playwright not available")
def test_real_browser_reads_js_table_and_paginates(tmp_path, monkeypatch):
    monkeypatch.setattr(egp_browser, "DEBUG_FILE", tmp_path / "dbg.txt")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/mock_egp.html"
        # 60 rows, page size capped at 25 -> 3 pages, so 'Next' must be used twice
        src = {**SRC, "url": url, "pages": 5, "delay": 0.1}
        recs = egp_browser.run_source(src, NOW)
        ids = sorted(r["id"] for r in recs)
        assert len(ids) == 60 and ids[0] == "egp-1177000" and ids[-1] == "egp-1177059"
        one = {r["id"]: r for r in recs}["egp-1177001"]
        assert one["nature"] == "Goods" and one["method"] == "LTM" and one["deadline"] == "2026-12-02"
        assert one["organization"].startswith("XEN, Rangpur") and one["ref_no"] == "MOWR/BWDB/2026/101"
        assert "headers:" in (tmp_path / "dbg.txt").read_text()
    finally:
        srv.shutdown()
