from concurrent.futures import ThreadPoolExecutor
from datetime import date
import sqlite3
import pytest
from database.db import Database
from services.attendance_service import AttendanceError


def test_schema_and_empty_count(app):
    with app.extensions['database'].connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    assert app.extensions['database'].stats()['total'] == 0


@pytest.mark.parametrize('connected,model_phase,faces', [(False,'error',[]),(True,'ready',[]),(True,'loading',[]),(True,'ready',[{'box':[0,0,1,1],'confidence':.9}]*2)])
def test_manual_mark_needs_no_camera_or_detection(app, connected, model_phase, faces):
    service = app.extensions['attendance']
    app.extensions['camera'].connected = connected
    service.detector.phase = model_phase
    service.faces = service.eligible = faces
    assert service.mark()['stats']['total'] == 1
    assert service.mark()['stats']['total'] == 2
    assert app.extensions['database'].pending_counts()[0]['total'] == 2


def test_atomic_duplicate_requests(app):
    service = app.extensions['attendance']
    def mark(_):
        try:
            service.mark('same-click')
            return True
        except AttendanceError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(mark,range(24))) == 1
    assert app.extensions['database'].stats()['total'] == 1


def test_reset_queues_higher_revision(app):
    db = app.extensions['database']
    db.insert('a', 'Manual entry')
    first = db.pending_counts()[0]
    assert db.reset() == 1
    latest = db.pending_counts()[0]
    assert latest['total'] == 0 and latest['revision'] > first['revision']
    db.acknowledge_count(first['day'], first['revision'])
    assert db.pending_counts() == [latest]


def test_restart_keeps_installation_and_outbox(app):
    db = app.extensions['database']
    db.insert('a', 'Manual entry')
    second = Database(db.path, 'Asia/Kolkata')
    assert second.pending_counts() == db.pending_counts()


def test_timezone_midnight_grouping(tmp_path):
    db = Database(tmp_path/'zone.sqlite3','Asia/Kolkata')
    with db.connect() as connection:
        for sid,stamp in [('a','2026-11-19T18:29:59+00:00'),('b','2026-11-19T18:30:00+00:00')]:
            connection.execute("INSERT INTO attendance_events(timestamp,camera_source,detection_session_id,status) VALUES(?,?,?,'recorded')",(stamp,'Manual entry',sid))
    assert db.stats(date(2026,11,19))['total'] == db.stats(date(2026,11,20))['total'] == 1
