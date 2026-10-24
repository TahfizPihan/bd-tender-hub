import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import normalize, parsers, webpage, worldbank  # noqa: E402

HERE = Path(__file__).parent
NOW = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)


# ---- World Bank -------------------------------------------------------------
WB = {"id": "worldbank-bd", "name": "World Bank (Bangladesh)", "type": "worldbank", "kind": "development"}


def wb_records():
    data = json.loads((HERE / "sample_worldbank.json").read_text(encoding="utf-8"))
    return worldbank.run_source({**WB, "notice_types": ["Invitation for Bids"]}, NOW,
                                getter=lambda params: data, log=lambda *a: None)


def test_worldbank_records():
    recs = {r["id"]: r for r in wb_records()}
    assert set(recs) == {"wb-OP00999001", "wb-OP00999002", "wb-OP00999003"}
    r = recs["wb-OP00999001"]
    assert r["link"].endswith("/procurement-detail/OP00999001")
    assert r["organization"] == "Chattogram Water Supply Improvement Project"
    assert r["kind"] == "development" and r["via"] == "worldbank"


def test_worldbank_deadline_comes_from_text_not_submission_date():
    recs = {r["id"]: r for r in wb_records()}
    assert recs["wb-OP00999001"]["deadline"] == "2026-11-24"   # "on or before 24 November 2026"
    assert recs["wb-OP00999002"]["deadline"] == "2026-11-05"
    assert recs["wb-OP00999003"]["deadline"] is None            # not the notice date


# ---- link-preserving text ---------------------------------------------------
def test_text_keeps_links_with_their_row():
    html = (HERE / "sample_bank.html").read_text(encoding="utf-8")
    text = parsers.html_to_text_with_links(html, "https://bank.test/tender-notice")
    lines = [l for l in text.splitlines() if "switches" in l]
    assert len(lines) == 1
    assert "12-Mar-2027" in lines[0]
    assert "<https://bank.test/public/assets/tender-notice/111_switches.pdf>" in lines[0]
    assert "About the bank" not in text                         # nav removed


# ---- generic AI web page source ---------------------------------------------
BANK = {"id": "bank-x", "name": "Bank X", "type": "ai_page", "kind": "private",
        "url": "https://bank.test/tender-notice"}
AI = [
    {"title": "Tender to supply 300 manageable access switches", "organization": "Bank X",
     "deadline": "2027-03-12", "published": None, "category": "ICT",
     "link": "https://bank.test/public/assets/tender-notice/111_switches.pdf"},
    {"title": "Tender for ATM/CRM network maintenance", "organization": None, "deadline": "24-Dec-2026",
     "category": "Nonsense", "link": "/public/assets/tender-notice/222_atm.pdf"},
    {"title": "short", "link": None},
]
HTML = (HERE / "sample_bank.html").read_text(encoding="utf-8")


def run(state, budget, extractor=lambda t, u, d: AI, fetcher=lambda u: HTML, robots=lambda u: True):
    return webpage.run_source(BANK, NOW, state, budget, fetcher=fetcher, extractor=extractor,
                              robots=robots, log=lambda *a: None, require_key=False)


def test_ai_page_records_and_validation():
    state, budget = {}, [5]
    recs = run(state, budget)
    assert [r["title"] for r in recs] == ["Tender to supply 300 manageable access switches",
                                          "Tender for ATM/CRM network maintenance"]
    assert recs[0]["deadline"] == "2027-03-12" and recs[0]["category"] == "ICT"
    assert recs[1]["deadline"] is None                          # non-ISO date from AI rejected
    assert recs[1]["link"] == "https://bank.test/public/assets/tender-notice/222_atm.pdf"
    assert recs[1]["category"] != "Nonsense"
    assert all(r["kind"] == "private" and r["via"] == "webpage" for r in recs)
    assert budget[0] == 4 and len(state) == 1


def test_unchanged_page_costs_nothing():
    state, budget = {}, [5]
    run(state, budget)
    calls = []
    recs = run(state, budget, extractor=lambda t, u, d: calls.append(1) or AI)
    assert recs == [] and calls == [] and budget[0] == 4


def test_changed_page_is_read_again():
    state, budget = {}, [5]
    run(state, budget)
    recs = run(state, budget, fetcher=lambda u: HTML.replace("ATM/CRM", "POS"))
    assert len(recs) == 2 and budget[0] == 3


def test_js_page_is_reported():
    with pytest.raises(RuntimeError):
        run({}, [5], fetcher=lambda u: "<html><body><div id='app'></div></body></html>")


def test_robots_disallow_is_respected():
    with pytest.raises(RuntimeError):
        run({}, [5], robots=lambda u: False)


def test_budget_zero_skips_ai():
    calls = []
    run({}, [0], extractor=lambda t, u, d: calls.append(1) or AI)
    assert calls == []


def test_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(webpage.Skipped):
        webpage.run_source(BANK, NOW, {}, [5])


def test_deadline_phrases():
    assert normalize.find_deadline("Bids must be received no later than 30 Nov 2026 at 10:00") == "2026-11-30"
