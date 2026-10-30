import json
from datetime import datetime, timezone
from pathlib import Path
from scraper import collect

RSS = """<rss><channel>
<item><title>Tender notice: interior fit-out of office - Daily Star</title><link>https://n.example/1</link><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Cricket team wins</title><link>https://n.example/2</link></item>
</channel></rss>"""


def test_news_lead_filter(monkeypatch):
    monkeypatch.setattr(collect, "fetch", lambda url: RSS)
    src = {"id": "lead-x", "name": "L", "type": "rss", "kind": "lead", "require_tender_word": True, "url": "u"}
    recs = collect.run_source(src, datetime.now(timezone.utc))
    assert len(recs) == 1 and recs[0]["kind"] == "lead"
    assert recs[0]["category"] == "Interior & fit-out"


def test_sources_json_valid():
    data = json.loads((Path(collect.__file__).parent.parent / "sources.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data]
    assert len(ids) == len(set(ids))
    assert any(s["id"] == "bppa-govt" and s["enabled"] for s in data)
    assert sum(1 for s in data if s["id"].startswith("lead-") and s["enabled"]) == 3
