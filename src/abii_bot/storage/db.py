"""ذخیره‌سازی SQLite — بدون نیاز به سرور دیتابیس، قابل ارتقا به PostgreSQL در فاز بعد."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..models import Lead, utcnow

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    url           TEXT,
    title         TEXT,
    category      TEXT,
    city          TEXT,
    district      TEXT,
    price         TEXT,
    seller_name   TEXT,
    phones        TEXT,
    emails        TEXT,
    description   TEXT,
    quality_score INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'new',
    first_seen    TEXT,
    last_seen     TEXT,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_phones ON leads(phones);
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    platform TEXT,
    spec TEXT,
    new_count INTEGER, updated_count INTEGER, duplicate_count INTEGER, error_count INTEGER
);
"""

_COLS = (
    "source, source_id, url, title, category, city, district, price, seller_name, "
    "phones, emails, description, quality_score, status, first_seen, last_seen"
)


class LeadStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- CRUD ----------
    def get(self, source: str, source_id: str) -> Lead | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM leads WHERE source=? AND source_id=?",
                (source, source_id),
            ).fetchone()
        return self._row_to_lead(row) if row else None

    def upsert(self, lead: Lead) -> None:
        phones = json.dumps(lead.phones, ensure_ascii=False)
        emails = json.dumps(lead.emails, ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO leads ({cols})
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    url=excluded.url, title=excluded.title, category=excluded.category,
                    city=excluded.city, district=excluded.district, price=excluded.price,
                    seller_name=excluded.seller_name, phones=excluded.phones,
                    emails=excluded.emails, description=excluded.description,
                    quality_score=excluded.quality_score, status=excluded.status,
                    last_seen=excluded.last_seen
                """.format(cols=_COLS),
                (
                    lead.source, lead.source_id, lead.url, lead.title, lead.category,
                    lead.city, lead.district, lead.price, lead.seller_name,
                    phones, emails, lead.description, lead.quality_score, lead.status,
                    lead.first_seen.isoformat(), lead.last_seen.isoformat(),
                ),
            )

    def all_leads(self) -> list[Lead]:
        with self._conn() as conn:
            rows = conn.execute(f"SELECT {_COLS} FROM leads ORDER BY quality_score DESC").fetchall()
        return [self._row_to_lead(r) for r in rows]

    def record_run(self, spec: dict, counts: dict, started_at: datetime) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO scan_runs (started_at, finished_at, platform, spec,
                   new_count, updated_count, duplicate_count, error_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    started_at.isoformat(), utcnow().isoformat(), spec.get("platform", "?"),
                    json.dumps(spec, ensure_ascii=False),
                    counts.get("new", 0), counts.get("updated", 0),
                    counts.get("duplicate", 0), counts.get("errors", 0),
                ),
            )

    # ---------- helpers ----------
    @staticmethod
    def _row_to_lead(row: sqlite3.Row) -> Lead:
        return Lead(
            source=row["source"], source_id=row["source_id"], url=row["url"] or "",
            title=row["title"], category=row["category"], city=row["city"],
            district=row["district"], price=row["price"], seller_name=row["seller_name"],
            phones=json.loads(row["phones"] or "[]"),
            emails=json.loads(row["emails"] or "[]"),
            description=row["description"],
            quality_score=row["quality_score"] or 0, status=row["status"] or "new",
            first_seen=_parse_dt(row["first_seen"]), last_seen=_parse_dt(row["last_seen"]),
        )


def _parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return utcnow()
