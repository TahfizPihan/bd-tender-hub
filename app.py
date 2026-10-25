from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from backend.database import ensure_db, get_filters, get_summary, get_tender_by_id, get_tenders

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="docs", static_url_path="")


@app.get("/")
def index():
    return send_from_directory("docs", "index.html")


@app.get("/tender/<tender_id>")
def tender_page(tender_id: str):
    return send_from_directory("docs", "detail.html")


@app.get("/api/tenders")
def api_tenders():
    ensure_db()
    query = {
        "q": request.args.get("q", ""),
        "status": request.args.get("status", "all"),
        "source": request.args.get("source", ""),
        "category": request.args.get("category", ""),
        "kind": request.args.get("kind", ""),
        "location": request.args.get("location", ""),
        "sort": request.args.get("sort", "deadline"),
    }
    return jsonify({"tenders": get_tenders(query)})


@app.get("/api/tender/<tender_id>")
def api_tender_detail(tender_id: str):
    ensure_db()
    tender = get_tender_by_id(tender_id)
    return jsonify({"tender": tender})


@app.get("/api/filters")
def api_filters():
    ensure_db()
    return jsonify(get_filters())


@app.get("/api/summary")
def api_summary():
    ensure_db()
    return jsonify(get_summary())


@app.post("/api/sync")
def api_sync():
    try:
        subprocess.run(["python", "-m", "scraper.collect"], cwd=str(ROOT), check=True)
        ensure_db()
        return jsonify({"ok": True, "message": "Tender data refreshed."})
    except subprocess.CalledProcessError as exc:
        return jsonify({"ok": False, "message": f"Collection failed with exit code {exc.returncode}."}), 500


@app.route("/<path:path>")
def serve_static(path: str):
    return send_from_directory("docs", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
