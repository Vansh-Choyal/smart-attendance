import sqlite3
import uuid
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
                CREATE TABLE IF NOT EXISTS exhibition_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), device_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS exhibition_outbox (
                    day TEXT PRIMARY KEY, revision INTEGER NOT NULL, total INTEGER NOT NULL
                );
            """)
            db.execute('INSERT OR IGNORE INTO exhibition_state(id,device_id) VALUES(1,?)', (str(uuid.uuid4()),))

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
            self._queue_count(db, self.today())
            return dict(id=cursor.lastrowid, timestamp=stamp, camera_source=source, status="recorded")

    def _queue_count(self, db, day):
        db.execute('UPDATE exhibition_state SET revision=revision+1 WHERE id=1')
        revision = db.execute('SELECT revision FROM exhibition_state WHERE id=1').fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM attendance_events WHERE timestamp>=? AND timestamp<?', self.bounds(day)).fetchone()[0]
        db.execute('INSERT INTO exhibition_outbox(day,revision,total) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET revision=excluded.revision,total=excluded.total', (day.isoformat(), revision, total))

    def pending_counts(self):
        with self.connect() as db:
            device = db.execute('SELECT device_id FROM exhibition_state WHERE id=1').fetchone()[0]
            return [dict(row) | {'device_id': device} for row in db.execute('SELECT day,revision,total FROM exhibition_outbox ORDER BY revision')]

    def acknowledge_count(self, day, revision):
        with self.connect() as db:
            db.execute('DELETE FROM exhibition_outbox WHERE day=? AND revision=?', (day, revision))

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
            self._queue_count(db, self.today())
            return cursor.rowcount
