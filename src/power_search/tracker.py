"""Cost and usage tracking — SQLite-backed."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from dataclasses import dataclass

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
            self._conn = sqlite3.connect(str(db_path))
            self._conn.execute("""
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
                )
            """)
            self._conn.commit()
        return self._conn

    def record(self, provider: str, intent: str, query: str,
               cost: float, tokens_in: int = 0, tokens_out: int = 0,
               elapsed_ms: int = 0):
        """Record a single API call."""
        self._db().execute(
            "INSERT INTO usage (ts, provider, intent, query, cost, tokens_in, tokens_out, elapsed_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), provider, intent, query, cost, tokens_in, tokens_out, elapsed_ms),
        )
        self._db().commit()

    def today(self) -> UsageSummary:
        """Get today's usage."""
        return self._summary_for_date(date.today().isoformat())

    def total(self) -> UsageSummary:
        """Get all-time usage."""
        return self._summary("1=1")

    def by_provider(self) -> dict[str, float]:
        """Total cost by provider, all time."""
        rows = self._db().execute(
            "SELECT provider, SUM(cost) FROM usage GROUP BY provider"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def today_cost(self) -> float:
        """Quick check for budget enforcement."""
        row = self._db().execute(
            "SELECT COALESCE(SUM(cost), 0) FROM usage WHERE ts >= ?",
            (date.today().isoformat(),),
        ).fetchone()
        return row[0]

    def recent(self, n: int = 10) -> list[dict]:
        """Last N queries."""
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
