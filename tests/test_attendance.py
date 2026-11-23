from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace
import sqlite3
import time

import pytest

from app import create_app
from database.db import Database
from services.attendance_service import AttendanceError
from conftest import FakeCamera, ready


def test_initialization_schema_privacy(app):
    db = app.extensions['database']
    with db.connect() as connection:
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(attendance_events)')}
        assert columns == {'id','timestamp','camera_source','detection_session_id','status'}
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
    assert db.stats()['total'] == 0


def test_stable_face_required(app, face):
    service = app.extensions['attendance']
    service.observe([face],time.monotonic(),1)
    assert service.snapshot()['state'] == 'FACE_DETECTED'
    with pytest.raises(AttendanceError): service.mark(service.session_id)
    session_id = ready(app,face)
    assert service.snapshot()['ready']
    result = service.mark(session_id)
    assert result['stats']['total'] == 1
    assert result['event']['camera_source'] == 'Built-in camera · 0'
    assert service.snapshot()['state'] == 'RECORDED'


def test_atomic_duplicate_requests(app, face):
    service = app.extensions['attendance']
    sid = ready(app,face)
    def request(_):
        try: service.mark(sid); return 'recorded'
        except AttendanceError: return 'rejected'
    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(request,range(32)))
    assert outcomes.count('recorded') == 1
    assert app.extensions['database'].stats()['total'] == 1


def test_concurrent_http_requests(app, face):
    sid = ready(app,face)
    def mark(_):
        client = app.test_client()
        with client.session_transaction() as session:
            session['operator'],session['csrf'] = True,'parallel-test'
        return client.post('/api/attendance/mark',json={'session_id':sid},headers={'X-CSRF-Token':'parallel-test'}).status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(mark,range(16)))
    assert responses.count(201) == 1
    assert responses.count(409) == 15


def test_database_unique_session(app):
    db = app.extensions['database']
    db.insert('unique-session','Built-in camera · 0')
    with pytest.raises(sqlite3.IntegrityError): db.insert('unique-session','Built-in camera · 0')
    assert db.stats()['total'] == 1


@pytest.mark.parametrize('faces', [[], [{'box':[0,0,.1,.1],'confidence':.95}], [{'box':[.4,.3,.6,.6],'confidence':.59}]])
def test_invalid_detection(app,faces):
    service = app.extensions['attendance']
    service.observe(faces,time.monotonic(),1)
    assert not service.snapshot()['ready']
    with pytest.raises(AttendanceError): service.mark('anything')
    assert app.extensions['database'].stats()['total'] == 0


def test_multiple_faces_reset_stability(app,face):
    service = app.extensions['attendance']
    ready(app,face)
    service.observe([face,face],time.monotonic(),1)
    assert not service.snapshot()['ready']
    assert service.snapshot()['faces_in_zone'] == 2
    with pytest.raises(AttendanceError) as error: service.mark('anything')
    assert error.value.code == 'multiple_faces'
    service.observe([face],time.monotonic(),1)
    assert service.state == 'FACE_DETECTED'


def test_outside_face_does_not_block_single_inside(app,face):
    service = app.extensions['attendance']
    ready(app,face)
    service.observe([face,{'box':[0,0,.1,.1],'confidence':.9}],time.monotonic(),1)
    assert service.snapshot()['ready']


def test_stale_result_and_stale_click_rejected(app,face):
    service = app.extensions['attendance']
    sid = ready(app,face)
    with pytest.raises(AttendanceError) as error: service.mark('old-client-session')
    assert error.value.code == 'session_changed'
    service.last_observation -= 2
    with pytest.raises(AttendanceError): service.mark(sid)
    service.observe([face],time.monotonic()-2,1)
    assert not service.snapshot()['ready']


def test_disconnection_invalidates_and_retains_recorded_lock(app,face):
    service, camera = app.extensions['attendance'],app.extensions['camera']
    sid = ready(app,face)
    camera.connected = False
    with pytest.raises(AttendanceError) as error: service.mark(sid)
    assert error.value.code == 'camera_disconnected'
    camera.connected = True
    sid = ready(app,face)
    service.mark(sid)
    camera.connected = False
    service.snapshot()
    camera.connected = True
    camera.generation += 1
    service.observe([face],time.monotonic(),camera.generation)
    assert service.locked and not service.snapshot()['ready']


def test_clear_duration_and_cooldown_both_required(app,face):
    service = app.extensions['attendance']
    clock = [100.0]
    service.clock = lambda: clock[0]
    def observe(faces, delta=0):
        clock[0] += delta
        service.observe(faces,clock[0],1)
    observe([face]); observe([face],.41)
    service.mark(service.session_id)
    observe([], .1)
    for _ in range(11): observe([], .1)
    assert service.locked  # clear for 1s, but cooldown not complete
    observe([face], .1)
    for _ in range(10): observe([face], .1)
    assert service.locked  # cooldown elapsed, but zone occupied
    observe([],.1)
    for _ in range(11): observe([], .1)
    assert not service.locked and service.state == 'IDLE'
    observe([face], .1); observe([face], .41)
    assert service.snapshot()['ready']
    service.mark(service.session_id)
    assert service.database.stats()['total'] == 2


def test_restart_preserves_database(app,face):
    service = app.extensions['attendance']
    service.mark(ready(app,face))
    second = create_app({'TESTING':True,'START_SERVICES':False,'DATA_DIR':app.config['DATA_DIR']},camera=FakeCamera(),detector=SimpleNamespace(phase='ready',error=None))
    assert second.extensions['database'].stats()['total'] == 1
    assert second.test_client().get('/api/attendance/stats').json['data']['total'] == 1
    second.extensions['close']()


def test_timezone_midnight_grouping(tmp_path):
    db = Database(tmp_path/'zone.sqlite3','Asia/Kolkata')
    with db.connect() as connection:
        for sid,stamp in [('a','2026-11-19T18:29:59+00:00'),('b','2026-11-19T18:30:00+00:00')]:
            connection.execute("INSERT INTO attendance_events(timestamp,camera_source,detection_session_id,status) VALUES(?,?,?,'recorded')",(stamp,'Camera',sid))
    assert db.stats(date(2026,11,19))['total'] == 1
    assert db.stats(date(2026,11,20))['total'] == 1


def test_model_error_disables_marking(app,face):
    service = app.extensions['attendance']
    sid = ready(app,face)
    service.detector.phase,service.detector.error = 'error','Model missing'
    assert not service.snapshot()['ready']
    with pytest.raises(AttendanceError): service.mark(sid)
