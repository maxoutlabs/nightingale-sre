"""
Nightingale SQLite Incident Database
Persistent storage for incident history, metrics, and config.
"""
import sqlite3
import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from nightingale.types import DashboardIncident, DashboardMetrics, IncidentStatus

DB_PATH = os.environ.get("NIGHTINGALE_DB_PATH", "nightingale.db")


def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db(db_path: str = DB_PATH):
    conn = _get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class IncidentDatabase:
    """
    SQLite-backed store for incident history, live status, and config.

    Schema:
      incidents  — one row per incident with full lifecycle data
      config     — key/value settings (e.g. auto_resolve_enabled)
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        with _db(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id                    TEXT PRIMARY KEY,
                    timestamp             TEXT NOT NULL,
                    repo                  TEXT NOT NULL DEFAULT '',
                    failure_type          TEXT NOT NULL DEFAULT '',
                    status                TEXT NOT NULL DEFAULT 'detected',
                    attempts              INTEGER DEFAULT 0,
                    confidence_score      REAL DEFAULT 0.0,
                    outcome               TEXT DEFAULT 'pending',
                    time_to_resolution_ms INTEGER DEFAULT 0,
                    root_cause            TEXT DEFAULT '',
                    fix_summary           TEXT DEFAULT '',
                    pr_url                TEXT DEFAULT '',
                    report_json           TEXT DEFAULT '{}',
                    created_at            TEXT,
                    updated_at            TEXT
                );

                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            # Insert defaults for config
            conn.execute("""
                INSERT OR IGNORE INTO config (key, value)
                VALUES ('auto_resolve_enabled', 'true')
            """)

    # ── Incident CRUD ──────────────────────────────────────────────────────────

    def upsert_incident(
        self,
        incident_id: str,
        repo: str = "",
        failure_type: str = "",
        status: str = IncidentStatus.DETECTED.value,
        attempts: int = 0,
        confidence_score: float = 0.0,
        outcome: str = "pending",
        time_to_resolution_ms: int = 0,
        root_cause: str = "",
        fix_summary: str = "",
        pr_url: str = "",
        report_json: str = "{}",
    ):
        now = datetime.now().isoformat()
        with _db(self.db_path) as conn:
            conn.execute("""
                INSERT INTO incidents
                    (id, timestamp, repo, failure_type, status, attempts,
                     confidence_score, outcome, time_to_resolution_ms,
                     root_cause, fix_summary, pr_url, report_json,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    repo                  = excluded.repo,
                    failure_type          = excluded.failure_type,
                    status                = excluded.status,
                    attempts              = excluded.attempts,
                    confidence_score      = excluded.confidence_score,
                    outcome               = excluded.outcome,
                    time_to_resolution_ms = excluded.time_to_resolution_ms,
                    root_cause            = excluded.root_cause,
                    fix_summary           = excluded.fix_summary,
                    pr_url                = excluded.pr_url,
                    report_json           = excluded.report_json,
                    updated_at            = excluded.updated_at
            """, (
                incident_id, now, repo, failure_type, status, attempts,
                confidence_score, outcome, time_to_resolution_ms,
                root_cause, fix_summary, pr_url, report_json,
                now, now,
            ))

    def update_status(self, incident_id: str, status: str):
        """Update just the status (called at each pipeline stage)."""
        with _db(self.db_path) as conn:
            conn.execute(
                "UPDATE incidents SET status=?, updated_at=? WHERE id=?",
                (status, datetime.now().isoformat(), incident_id),
            )

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with _db(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id=?", (incident_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_incidents(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with _db(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_dashboard_incidents(self, limit: int = 50) -> List[DashboardIncident]:
        rows = self.list_incidents(limit=limit)
        result = []
        for r in rows:
            result.append(DashboardIncident(
                id=r["id"],
                timestamp=r["timestamp"],
                repo=r["repo"],
                failure_type=r["failure_type"],
                status=r["status"],
                attempts=r["attempts"],
                confidence=r["confidence_score"],
                outcome=r["outcome"],
                time_to_resolution_ms=r["time_to_resolution_ms"],
                root_cause=r["root_cause"][:200] if r["root_cause"] else "",
                fix_summary=r["fix_summary"][:300] if r["fix_summary"] else "",
                pr_url=r["pr_url"] or "",
            ))
        return result

    def get_metrics(self) -> DashboardMetrics:
        with _db(self.db_path) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN outcome='resolved' THEN 1 ELSE 0 END)  AS resolved,
                    SUM(CASE WHEN outcome='escalated' THEN 1 ELSE 0 END) AS escalated,
                    AVG(CASE WHEN outcome='resolved' THEN confidence_score ELSE NULL END) AS avg_conf,
                    AVG(CASE WHEN time_to_resolution_ms > 0
                              THEN time_to_resolution_ms ELSE NULL END)  AS avg_ttr
                FROM incidents
            """).fetchone()

        total = row["total"] or 0
        resolved = row["resolved"] or 0
        escalated = row["escalated"] or 0
        avg_conf = float(row["avg_conf"] or 0.0)
        avg_ttr = int(row["avg_ttr"] or 0)

        return DashboardMetrics(
            total_incidents=total,
            auto_resolved=resolved,
            escalated=escalated,
            avg_confidence=round(avg_conf, 3),
            avg_resolution_ms=avg_ttr,
            success_rate=round(resolved / total, 3) if total > 0 else 0.0,
        )

    # ── Config ─────────────────────────────────────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        with _db(self.db_path) as conn:
            row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str):
        with _db(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?,?)",
                (key, value),
            )

    def is_auto_resolve_enabled(self) -> bool:
        return self.get_config("auto_resolve_enabled", "true").lower() == "true"

    def set_auto_resolve(self, enabled: bool):
        self.set_config("auto_resolve_enabled", "true" if enabled else "false")


# ── Global singleton ──────────────────────────────────────────────────────────

_db_instance: Optional[IncidentDatabase] = None


def get_db() -> IncidentDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = IncidentDatabase()
    return _db_instance
