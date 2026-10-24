import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import epaper  # noqa: E402

NOW = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)  # = 26 Oct 03:00 in Dhaka
SRC = {"id": "paper-x", "name": "Paper X (e-paper)", "type": "epaper_pages", "kind": "newspaper",
       "url_template": "https://ex.test/{yyyy}-{mm}-{dd}/p{page}.jpg", "pages": [3, 12]}

AI_OUT = [
    {"title": "Supply of Office Furniture for Zila Parishad", "organization": "Zila Parishad, Rangpur",
     "deadline": "2026-11-09", "category": "Furniture", "estimated_value_bdt": 2500000, "location": "Rangpur"},
    {"title": "সড়ক নির্মাণ কাজের দরপত্র", "organization": None, "deadline": "not a date", "category": "Weird"},
    {"title": "x", "organization": "too short title is dropped"},
    "garbage",
]


def test_template_uses_dhaka_date():
    urls = epaper.expand_urls(SRC, NOW)
    assert urls == ["https://ex.test/2026-10-26/p3.jpg", "https://ex.test/2026-10-26/p12.jpg"]


def test_bad_template_placeholder():
    with pytest.raises(ValueError):
        epaper.expand_urls({"url_template": "https://x/{bogus}"}, NOW)


def test_clean_items_validates():
    items = epaper.clean_items(AI_OUT, "https://ex.test/p3.jpg")
    assert [i["title"] for i in items] == ["Supply of Office Furniture for Zila Parishad", "সড়ক নির্মাণ কাজের দরপত্র"]
    assert items[0]["deadline"] == "2026-11-09" and items[0]["value_bdt"] == 2500000
    assert items[1]["deadline"] is None and "category" not in items[1]


def run(state, budget, fetch_ok=True):
    calls = []

    def fetcher(url):
        calls.append(url)
        if not fetch_ok:
            raise ValueError("404")
        return b"bytes", "image/jpeg"

    recs = epaper.run_source(SRC, NOW, state, budget, fetcher=lambda u: fetcher(u),
                             extractor=lambda d, m: AI_OUT, log=lambda *a: None, require_key=False)
    return recs, calls


def test_run_source_builds_records_and_marks_pages():
    state, budget = {}, [10]
    recs, calls = run(state, budget)
    assert len(calls) == 2 and budget[0] == 8 and len(state) == 2
    assert len(recs) == 4                       # 2 valid notices x 2 pages
    r = recs[0]
    assert r["via"] == "newspaper" and r["source"] == "Paper X (e-paper)"
    assert r["category"] == "Furniture" and r["organization"] == "Zila Parishad, Rangpur"
    assert r["link"] == "https://ex.test/2026-10-26/p3.jpg" and r["needs_ai"] is False


def test_pages_are_processed_once():
    state, budget = {}, [10]
    run(state, budget)
    recs, calls = run(state, budget)
    assert calls == [] and recs == []


def test_budget_limits_ai_calls():
    state, budget = {}, [1]
    recs, calls = run(state, budget)
    assert len(calls) == 1 and len(state) == 1


def test_missing_page_is_retried_next_time():
    state, budget = {}, [10]
    recs, calls = run(state, budget, fetch_ok=False)
    assert recs == [] and state == {} and budget[0] == 10


def test_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(epaper.Skipped):
        epaper.run_source(SRC, NOW, {}, [5])


def test_inbox_parsing(tmp_path, monkeypatch):
    f = tmp_path / "inbox.txt"
    f.write_text("# c\n\nhttps://a.test/p1.jpg | Prothom Alo\nhttps://a.test/p2.pdf\nnot a url\n", encoding="utf-8")
    monkeypatch.setattr(epaper, "INBOX_FILE", f)
    s = epaper.inbox_sources()
    assert [(x["name"], x["urls"]) for x in s] == [("Prothom Alo", ["https://a.test/p1.jpg"]),
                                                   ("Newspaper (manual)", ["https://a.test/p2.pdf"])]
