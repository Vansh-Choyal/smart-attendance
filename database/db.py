import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class Database:
    def __init__(self, path, timezone_name):
        self.path = str(path)
        self.zone = ZoneInfo(timezone_name)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attendance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    camera_source TEXT NOT NULL,
                    detection_session_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status = 'recorded')
                );
                CREATE INDEX IF NOT EXISTS attendance_timestamp ON attendance_events(timestamp);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def today(self):
        return datetime.now(self.zone).date()

    def bounds(self, day):
        start = datetime.combine(day, datetime.min.time(), self.zone)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), self.zone)
        return (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())

    def insert(self, session_id, source):
        stamp = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "INSERT INTO attendance_events(timestamp,camera_source,detection_session_id,status) VALUES (?,?,?,'recorded')",
                (stamp, source, session_id),
            )
            return dict(id=cursor.lastrowid, timestamp=stamp, camera_source=source, status="recorded")

    def stats(self, day=None):
        day = day or self.today()
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total, MAX(timestamp) AS last_check_in FROM attendance_events WHERE timestamp>=? AND timestamp<?",
                self.bounds(day),
            ).fetchone()
        return dict(row) | {"date": day.isoformat(), "timezone": str(self.zone)}

    def events(self, day=None, limit=50, before=None):
        day = day or self.today()
        params = list(self.bounds(day))
        query = "SELECT id,timestamp,camera_source,status FROM attendance_events WHERE timestamp>=? AND timestamp<?"
        if before is not None:
            query += " AND id<?"
            params.append(before)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def weekly(self, day=None):
        day = day or self.today()
        return [self.stats(day - timedelta(days=offset)) for offset in range(6, -1, -1)]

    def reset(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("DELETE FROM attendance_events WHERE timestamp>=? AND timestamp<?", self.bounds(self.today()))
            return cursor.rowcount
