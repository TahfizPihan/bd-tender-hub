from __future__ import annotations

from flask import Flask, jsonify, request, send_from_directory

from backend.database import ensure_db, get_filters, get_summary, get_tenders

app = Flask(__name__, static_folder="docs", static_url_path="")


@app.get("/")
def index():
    return send_from_directory("docs", "index.html")


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


@app.get("/api/filters")
def api_filters():
    ensure_db()
    return jsonify(get_filters())


@app.get("/api/summary")
def api_summary():
    ensure_db()
    return jsonify(get_summary())


@app.route("/<path:path>")
def serve_static(path: str):
    return send_from_directory("docs", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
