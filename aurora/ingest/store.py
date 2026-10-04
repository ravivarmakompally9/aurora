"""Edge time-series store with the PRD §9.3 schema (SQLite; TimescaleDB-compatible columns)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry(timestamp TEXT, asset_id TEXT, metric TEXT, value REAL, quality_flag TEXT);
CREATE INDEX IF NOT EXISTS telemetry_ts ON telemetry(timestamp);
CREATE TABLE IF NOT EXISTS forecasts(issued_at TEXT, target_time TEXT, variable TEXT, p10 REAL, p50 REAL, p90 REAL, model_version TEXT);
CREATE TABLE IF NOT EXISTS dispatch_plan(issued_at TEXT, target_time TEXT, asset_id TEXT, setpoint REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS events(timestamp TEXT, type TEXT, severity TEXT, message TEXT, acknowledged_by TEXT);
CREATE TABLE IF NOT EXISTS overrides(timestamp TEXT, user TEXT, action TEXT, previous_value TEXT, new_value TEXT, reason TEXT);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def telemetry(self, rows: list[tuple]):
        """rows: (timestamp, metric, value, flag); asset_id is the metric prefix."""
        with self.lock:
            self.conn.executemany("INSERT INTO telemetry VALUES (?,?,?,?,?)",
                                  [(str(ts), m.split(".")[0], m, v, f) for ts, m, v, f in rows])
            self.conn.commit()

    def forecasts(self, issued_at, rows: list[tuple], version: str):
        with self.lock:
            self.conn.executemany("INSERT INTO forecasts VALUES (?,?,?,?,?,?,?)",
                                  [(str(issued_at), str(t), var, p10, p50, p90, version) for t, var, p10, p50, p90 in rows])
            self.conn.commit()

    def plan(self, issued_at, rows: list[tuple]):
        with self.lock:
            self.conn.executemany("INSERT INTO dispatch_plan VALUES (?,?,?,?,?)",
                                  [(str(issued_at), str(t), a, v, r) for t, a, v, r in rows])
            self.conn.commit()

    def event(self, ts, kind: str, severity: str, message: str):
        with self.lock:
            self.conn.execute("INSERT INTO events VALUES (?,?,?,?,NULL)", (str(ts), kind, severity, message))
            self.conn.commit()

    def override(self, ts, user: str, action: str, prev, new, reason: str):
        with self.lock:
            self.conn.execute("INSERT INTO overrides VALUES (?,?,?,?,?,?)",
                              (str(ts), user, action, json.dumps(prev), json.dumps(new), reason))
            self.conn.commit()

    def query(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def latest(self, metric: str, n: int = 60) -> list[tuple]:
        return self.query("SELECT timestamp, value, quality_flag FROM telemetry WHERE metric=? ORDER BY rowid DESC LIMIT ?",
                          (metric, n))[::-1]
