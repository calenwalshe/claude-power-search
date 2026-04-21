"""Cost and usage tracking — SQLite-backed."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from power_search.config import get_config


@dataclass
class UsageSummary:
    total_cost: float
    total_queries: int
    by_provider: dict[str, dict]

    def __str__(self) -> str:
        lines = [f"Total: ${self.total_cost:.4f} across {self.total_queries} queries"]
        for name, data in self.by_provider.items():
            lines.append(f"  {name}: ${data['cost']:.4f} ({data['queries']} queries)")
        return "\n".join(lines)


class Tracker:
    def __init__(self):
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            db_path = get_config().db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    query TEXT NOT NULL,
                    cost REAL NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    elapsed_ms INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS search_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    query TEXT NOT NULL,
                    cost REAL NOT NULL DEFAULT 0.0,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    elapsed_ms INTEGER DEFAULT 0,
                    outcome TEXT NOT NULL,
                    candidates_tried TEXT NOT NULL DEFAULT '[]',
                    fallback_count INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    session_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_se_provider ON search_events(provider);
                CREATE INDEX IF NOT EXISTS idx_se_intent ON search_events(intent);
                CREATE INDEX IF NOT EXISTS idx_se_outcome ON search_events(outcome);
                CREATE INDEX IF NOT EXISTS idx_se_ts ON search_events(ts);
            """)
            self._conn.commit()
        return self._conn

    def record(self, provider: str, intent: str, query: str,
               cost: float, tokens_in: int = 0, tokens_out: int = 0,
               elapsed_ms: int = 0):
        """Record a single API call (legacy — prefer record_event)."""
        self._db().execute(
            "INSERT INTO usage (ts, provider, intent, query, cost, tokens_in, tokens_out, elapsed_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), provider, intent, query,
             cost, tokens_in, tokens_out, elapsed_ms),
        )
        self._db().commit()

    def record_event(
        self,
        provider: str,
        intent: str,
        query: str,
        cost: float,
        outcome: str,
        candidates_tried: list[str],
        fallback_count: int,
        elapsed_ms: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """Record a search event with full routing context (L0 telemetry)."""
        self._db().execute(
            """INSERT INTO search_events
               (ts, provider, intent, query, cost, tokens_in, tokens_out,
                elapsed_ms, outcome, candidates_tried, fallback_count,
                error_type, session_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                provider, intent, query, cost,
                tokens_in, tokens_out, elapsed_ms,
                outcome,
                json.dumps(candidates_tried),
                fallback_count,
                error_type,
                session_id,
            ),
        )
        self._db().commit()

    def recent_events(self, n: int = 10, intent: Optional[str] = None) -> list[dict]:
        """Last N search events, newest first."""
        if intent:
            rows = self._db().execute(
                """SELECT * FROM search_events WHERE intent = ?
                   ORDER BY id DESC LIMIT ?""",
                (intent, n),
            ).fetchall()
        else:
            rows = self._db().execute(
                "SELECT * FROM search_events ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["candidates_tried"] = json.loads(d.get("candidates_tried") or "[]")
            result.append(d)
        return result

    def route_stats(self, intent: Optional[str] = None) -> list[dict]:
        """Per-provider success rates, latency, and fallback stats.

        Returns a list of dicts sorted by provider name, optionally filtered
        to a single intent. Used by memory-informed routing.
        """
        where = "WHERE intent = ?" if intent else ""
        params = (intent,) if intent else ()
        rows = self._db().execute(
            f"""SELECT
                    provider,
                    intent,
                    COUNT(*) AS total,
                    SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success,
                    AVG(elapsed_ms) AS avg_latency_ms,
                    AVG(fallback_count) AS avg_fallback_count,
                    SUM(cost) AS total_cost
                FROM search_events
                {where}
                GROUP BY provider, intent
                ORDER BY provider, intent""",
            params,
        ).fetchall()
        result = []
        for r in rows:
            total = r["total"] or 0
            succ = r["success"] or 0
            result.append({
                "provider": r["provider"],
                "intent": r["intent"],
                "total": total,
                "success": succ,
                "success_rate": succ / total if total else 0.0,
                "avg_latency_ms": round(r["avg_latency_ms"] or 0, 1),
                "avg_fallback_count": round(r["avg_fallback_count"] or 0, 3),
                "total_cost": round(r["total_cost"] or 0, 6),
            })
        return result

    def today(self) -> UsageSummary:
        return self._summary_for_date(date.today().isoformat())

    def total(self) -> UsageSummary:
        return self._summary("1=1")

    def by_provider(self) -> dict[str, float]:
        rows = self._db().execute(
            "SELECT provider, SUM(cost) FROM usage GROUP BY provider"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def today_cost(self) -> float:
        row = self._db().execute(
            "SELECT COALESCE(SUM(cost), 0) FROM usage WHERE ts >= ?",
            (date.today().isoformat(),),
        ).fetchone()
        return row[0]

    def recent(self, n: int = 10) -> list[dict]:
        rows = self._db().execute(
            "SELECT ts, provider, intent, query, cost FROM usage ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [
            {"ts": r[0], "provider": r[1], "intent": r[2], "query": r[3], "cost": r[4]}
            for r in rows
        ]

    def _summary_for_date(self, date_prefix: str) -> UsageSummary:
        return self._summary(f"ts >= '{date_prefix}'")

    def _summary(self, where: str) -> UsageSummary:
        db = self._db()
        row = db.execute(
            f"SELECT COALESCE(SUM(cost), 0), COUNT(*) FROM usage WHERE {where}"
        ).fetchone()
        providers = db.execute(
            f"SELECT provider, SUM(cost), COUNT(*) FROM usage WHERE {where} GROUP BY provider"
        ).fetchall()
        return UsageSummary(
            total_cost=row[0],
            total_queries=row[1],
            by_provider={r[0]: {"cost": r[1], "queries": r[2]} for r in providers},
        )


# Module-level singleton
usage = Tracker()
