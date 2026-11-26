import io
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from cryptography import x509

from app import create_app
from services.camera_service import public_source,validate_source
from services.local_https import ensure_certificate


@pytest.fixture
def browser_app(tmp_path):
    app = create_app({'START_SERVICES':False,'TESTING':True,'DATA_DIR':tmp_path,'LAN_MODE':True},detector=SimpleNamespace(phase='ready',error=None))
    yield app
    app.extensions['close']()


@pytest.fixture
def phone(browser_app):
    client = browser_app.test_client()
    with client.session_transaction() as session:
        session['operator'],session['csrf'] = True,'browser-test'
    client.csrf = 'browser-test'
    return client


@pytest.fixture
def jpeg():
    # A textured fixture exceeds the normal 8KB JSON body limit.
    image = np.random.default_rng(10).integers(0,255,(480,640,3),dtype=np.uint8)
    return cv2.imencode('.jpg',image)[1].tobytes()


def start(phone):
    result = phone.post('/api/camera/browser/start',json={},headers={'X-CSRF-Token':phone.csrf})
    assert result.status_code == 200,result.json
    return result.json['data']


def upload(phone,lease,jpeg,**overrides):
    headers = {'X-CSRF-Token':phone.csrf,'X-Camera-Session':lease['publisher_token'],
               'X-Capture-Ticket':lease['capture_ticket'],'X-Frame-Sequence':str(lease['sequence'])}
    headers.update(overrides)
    return phone.post('/api/camera/browser/frame',data=jpeg,content_type='image/jpeg',headers=headers)


def test_browser_publish_uses_shared_camera_pipeline(browser_app,phone,jpeg):
    lease = start(phone)
    assert not browser_app.extensions['camera'].status()['connected']
    result = upload(phone,lease,jpeg)
    assert len(jpeg)>8192 and result.status_code==200,result.json
    camera = browser_app.extensions['camera']
    assert camera.status()['connected']
    assert camera.status()['source']['type']=='browser'
    assert camera.latest()[0].shape == (480,640,3)
    assert camera.encoded()[0] == jpeg
    assert camera.process is None
    assert browser_app.extensions['camera_store'].load()=={'type':'browser'}
    assert not {'publisher_token','capture_ticket'} & camera.status().keys()
    assert 'browser' in validate_source({'type':'browser'}).values()


def test_freshness_tickets_reject_delayed_frames_and_renew(browser_app,phone,jpeg):
    lease = start(phone)
    browser_app.extensions['camera'].browser_ticket_time -= 2
    response = upload(phone,lease,jpeg)
    assert response.status_code==409 and response.json['error']['code']=='capture_expired'
    assert not browser_app.extensions['camera'].status()['connected']
    renewed = phone.post('/api/camera/browser/renew',json={'publisher_token':lease['publisher_token']},headers={'X-CSRF-Token':phone.csrf})
    assert renewed.status_code==200
    lease.update(renewed.json['data'])
    assert upload(phone,lease,jpeg).status_code==200


def test_uploaded_image_is_not_a_detection_but_manual_mark_is_allowed(browser_app,phone,jpeg):
    lease = start(phone); assert upload(phone,lease,jpeg).status_code==200
    service = browser_app.extensions['attendance']
    assert not service.snapshot()['ready']
    response = phone.post('/api/attendance/mark',json={'face_detected':True},headers={'X-CSRF-Token':phone.csrf})
    assert response.status_code==201
    assert service.database.stats()['total']==1


def test_replayed_and_out_of_order_frames_are_rejected(phone,jpeg):
    lease = start(phone)
    assert upload(phone,lease,jpeg,**{'X-Frame-Sequence':'2'}).json['error']['code']=='frame_out_of_order'
    assert upload(phone,lease,jpeg).status_code==200
    assert upload(phone,lease,jpeg).status_code==409


def test_other_phone_cannot_steal_connected_publisher(browser_app,phone,jpeg):
    lease = start(phone); assert upload(phone,lease,jpeg).status_code==200
    other = browser_app.test_client()
    with other.session_transaction() as session:
        session['operator'],session['csrf'] = True,'other-test'
    result = other.post('/api/camera/browser/start',json={},headers={'X-CSRF-Token':'other-test'})
    assert result.status_code==409 and result.json['error']['code']=='publisher_busy'
    assert browser_app.extensions['camera'].status()['connected']


def test_first_frame_lease_also_blocks_a_competing_phone(browser_app,phone):
    start(phone)
    other = browser_app.test_client()
    with other.session_transaction() as session:
        session['operator'],session['csrf'] = True,'other-test'
    result = other.post('/api/camera/browser/start',json={},headers={'X-CSRF-Token':'other-test'})
    assert result.status_code==409 and result.json['error']['code']=='publisher_busy'


def test_navigation_rotates_publisher_without_old_page_stopping_it(browser_app,phone,jpeg):
    old = start(phone); assert upload(phone,old,jpeg).status_code==200
    new = start(phone)
    response = phone.post('/api/camera/browser/stop',json={'publisher_token':old['publisher_token']},headers={'X-CSRF-Token':phone.csrf})
    assert response.status_code==409
    assert upload(phone,new,jpeg).status_code==200
    assert browser_app.extensions['camera'].status()['connected']


def test_stopping_browser_invalidates_overlay_but_manual_marks_continue(browser_app,phone,jpeg,face):
    lease = start(phone); assert upload(phone,lease,jpeg).status_code==200
    camera,service = browser_app.extensions['camera'],browser_app.extensions['attendance']
    service.observe([face],time.monotonic(),camera.generation)
    service.stable_since -= .5
    service.observe([face],time.monotonic(),camera.generation)
    service.mark(service.session_id)
    result = phone.post('/api/camera/browser/stop',json={'publisher_token':lease['publisher_token']},headers={'X-CSRF-Token':phone.csrf})
    assert result.status_code==200
    assert not camera.status()['connected'] and not service.snapshot()['ready']
    new = start(phone); assert upload(phone,new,jpeg).status_code==200
    service.observe([face],time.monotonic(),camera.generation)
    assert not service.snapshot()['ready']
    assert service.mark()['stats']['total'] == 2


def test_invalid_and_oversized_jpeg_rejected(browser_app,phone,jpeg):
    lease = start(phone)
    assert upload(phone,lease,b'not a jpeg').status_code==400
    assert upload(phone,lease,b'x'*(2*1024*1024+1)).status_code==413
    assert upload(phone,lease,jpeg,**{'X-Camera-Session':'wrong'}).status_code==409
    from PIL import Image
    out = io.BytesIO(); Image.new('RGB',(2100,32)).save(out,format='JPEG')
    assert upload(phone,lease,out.getvalue()).status_code==400
    assert not browser_app.extensions['camera'].status()['connected']


def test_capture_authentication_csrf_and_https(browser_app,phone):
    client = browser_app.test_client(); token = client.get('/api/auth/status').json['data']['csrf']
    assert client.post('/api/camera/browser/start',json={},headers={'X-CSRF-Token':token}).status_code==401
    assert phone.post('/api/camera/browser/start',json={}).status_code==403
    response = phone.post('/api/camera/browser/start',json={},headers={'X-CSRF-Token':phone.csrf},environ_overrides={'REMOTE_ADDR':'192.168.1.30'})
    assert response.status_code==403 and response.json['error']['code']=='https_required'
    assert phone.get('/setup').headers['Permissions-Policy']=='camera=(self), microphone=(), geolocation=()'


def test_no_browser_frames_persisted(browser_app,phone,jpeg):
    lease = start(phone); assert upload(phone,lease,jpeg).status_code==200
    assert not any(p.suffix.lower() in {'.jpg','.jpeg','.png','.mp4','.npy','.npz'} for p in browser_app.config['DATA_DIR'].rglob('*'))


def test_https_certificate_is_reused_and_has_lan_ip(tmp_path):
    cert,key = ensure_certificate(tmp_path,['127.0.0.1','192.168.1.4'])
    content = cert.read_bytes()
    names = x509.load_pem_x509_certificate(content).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    import ipaddress
    assert x509.IPAddress(ipaddress.ip_address('192.168.1.4')) in names
    assert key.exists()
    assert ensure_certificate(tmp_path,['127.0.0.1','192.168.1.4'])[0].read_bytes()==content
