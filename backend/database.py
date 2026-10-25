from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tenders.db"
JSON_PATH = ROOT / "docs" / "tenders.json"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def ensure_db() -> sqlite3.Connection:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id TEXT PRIMARY KEY,
            title TEXT,
            organization TEXT,
            category TEXT,
            deadline TEXT,
            published TEXT,
            source TEXT,
            source_id TEXT,
            kind TEXT,
            location TEXT,
            summary TEXT,
            link TEXT,
            first_seen TEXT,
            last_seen TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_deadline ON tenders(deadline)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_source ON tenders(source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_category ON tenders(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_kind ON tenders(kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_location ON tenders(location)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status)")
    conn.commit()
    sync_from_json(conn)
    return conn


def _compute_status(deadline: str | None) -> str:
    if not deadline:
        return "open"
    try:
        d = date.fromisoformat(deadline)
    except ValueError:
        return "open"
    today = date.today()
    if d < today:
        return "closed"
    if (d - today).days <= 7:
        return "soon"
    return "open"


def sync_from_json(conn: sqlite3.Connection) -> None:
    if not JSON_PATH.exists():
        return
    try:
        payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    tenders = payload.get("tenders", []) if isinstance(payload, dict) else []
    if not tenders:
        return

    for tender in tenders:
        if not tender.get("id"):
            continue
        deadline = tender.get("deadline")
        location = tender.get("location") or tender.get("district") or ""
        kind = tender.get("kind") or "public"
        status = _compute_status(deadline)
        conn.execute(
            """
            INSERT INTO tenders (
                id, title, organization, category, deadline, published, source, source_id,
                kind, location, summary, link, first_seen, last_seen, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                organization=excluded.organization,
                category=excluded.category,
                deadline=excluded.deadline,
                published=excluded.published,
                source=excluded.source,
                source_id=excluded.source_id,
                kind=excluded.kind,
                location=excluded.location,
                summary=excluded.summary,
                link=excluded.link,
                first_seen=excluded.first_seen,
                last_seen=excluded.last_seen,
                status=excluded.status
            """,
            (
                tender.get("id"),
                tender.get("title") or "",
                tender.get("organization") or "",
                tender.get("category") or "Other",
                deadline,
                tender.get("published") or "",
                tender.get("source") or tender.get("source_id") or "Unknown",
                tender.get("source_id") or "",
                kind,
                location,
                tender.get("summary") or "",
                tender.get("link") or "",
                tender.get("first_seen") or "",
                tender.get("last_seen") or "",
                status,
            ),
        )
    conn.commit()


def _status_filter(status: str | None) -> str:
    status = (status or "all").strip().lower()
    if status in ("", "all"):
        return "1=1"
    if status == "open":
        return "(deadline IS NULL OR deadline >= date('now'))"
    if status == "soon":
        return "deadline IS NOT NULL AND deadline >= date('now') AND (julianday(deadline) - julianday(date('now'))) <= 7"
    if status == "closed":
        return "deadline IS NOT NULL AND deadline < date('now')"
    return "1=1"


def get_tenders(filters: dict | None = None) -> list[dict]:
    conn = ensure_db()
    params: list[str] = []
    clauses: list[str] = []
    filters = filters or {}

    q = (filters.get("q") or "").strip()
    if q:
        q_like = f"%{q.lower()}%"
        clauses.append("(LOWER(title) LIKE ? OR LOWER(organization) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(location) LIKE ? OR LOWER(source) LIKE ?)")
        params.extend([q_like, q_like, q_like, q_like, q_like])

    source = (filters.get("source") or "").strip()
    if source:
        clauses.append("source = ?")
        params.append(source)

    category = (filters.get("category") or "").strip()
    if category:
        clauses.append("category = ?")
        params.append(category)

    kind = (filters.get("kind") or "").strip()
    if kind:
        clauses.append("kind = ?")
        params.append(kind)

    location = (filters.get("location") or "").strip()
    if location:
        clauses.append("LOWER(location) = LOWER(?)")
        params.append(location)

    status = (filters.get("status") or "all").strip().lower()
    clauses.append(_status_filter(status))

    where_sql = " AND ".join(clauses) if clauses else "1=1"
    sort = (filters.get("sort") or "deadline").strip().lower()
    if sort == "new":
        order_sql = "ORDER BY first_seen DESC, deadline ASC"
    elif sort == "source":
        order_sql = "ORDER BY source ASC, title ASC"
    else:
        order_sql = "ORDER BY CASE WHEN deadline IS NULL THEN '9999-12-31' ELSE deadline END ASC, first_seen DESC"

    rows = conn.execute(f"SELECT * FROM tenders WHERE {where_sql} {order_sql}", params).fetchall()
    return [dict(row) for row in rows]


def get_filters() -> dict:
    conn = ensure_db()
    return {
        "sources": [row[0] for row in conn.execute("SELECT DISTINCT source FROM tenders WHERE source != '' ORDER BY source ASC").fetchall()],
        "categories": [row[0] for row in conn.execute("SELECT DISTINCT category FROM tenders WHERE category != '' ORDER BY category ASC").fetchall()],
        "types": [row[0] for row in conn.execute("SELECT DISTINCT kind FROM tenders WHERE kind != '' ORDER BY kind ASC").fetchall()],
        "locations": [row[0] for row in conn.execute("SELECT DISTINCT location FROM tenders WHERE location != '' ORDER BY location ASC").fetchall()],
    }


def get_summary() -> dict:
    conn = ensure_db()
    total = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    open_count = conn.execute("SELECT COUNT(*) FROM tenders WHERE deadline IS NULL OR deadline >= date('now')").fetchone()[0]
    soon_count = conn.execute("SELECT COUNT(*) FROM tenders WHERE deadline IS NOT NULL AND deadline >= date('now') AND (julianday(deadline) - julianday(date('now'))) <= 7").fetchone()[0]
    closed_count = conn.execute("SELECT COUNT(*) FROM tenders WHERE deadline IS NOT NULL AND deadline < date('now')").fetchone()[0]
    return {"total": total, "open": open_count, "soon": soon_count, "closed": closed_count}
