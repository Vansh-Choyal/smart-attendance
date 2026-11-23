import json
import time

import pytest

from conftest import ready
from services.camera_service import validate_source, public_source
from services.secure_store import SecureStore


@pytest.mark.parametrize('route',['/setup','/dashboard','/camera'])
def test_all_primary_pages_and_empty_rendering(client,route):
    response = client.get(route)
    assert response.status_code == 200
    assert b'Attend' in response.data
    assert b'csrf-token' in response.data
    assert b'Content-Security-Policy' not in response.data
    assert response.headers['X-Frame-Options'] == 'DENY'


@pytest.mark.parametrize('route',['/api/camera/status','/api/detection/status','/api/attendance/stats','/api/attendance/events','/api/attendance/weekly','/api/auth/status'])
def test_read_endpoints(client,route):
    response = client.get(route)
    assert response.status_code == 200 and response.json['ok']


def test_authentication_and_csrf(client):
    assert client.post('/api/attendance/mark',json={}).status_code == 403
    csrf = client.get('/api/auth/status').json['data']['csrf']
    assert client.post('/api/attendance/mark',json={},headers={'X-CSRF-Token':csrf}).status_code == 401
    assert client.post('/api/camera/select',json={'type':'webcam','index':0},headers={'X-CSRF-Token':csrf}).status_code == 401
    assert client.post('/api/attendance/reset',json={},headers={'X-CSRF-Token':csrf}).status_code == 401
    assert client.get('/api/camera/feed').status_code == 401
    assert client.get('/api/cameras').status_code == 401


def test_mark_endpoint_ignores_client_counts(operator,app,face):
    sid = ready(app,face)
    response = operator.post('/api/attendance/mark',json={'session_id':sid,'count':999,'face_detected':True},headers={'X-CSRF-Token':operator.csrf})
    assert response.status_code == 201
    assert response.json['data']['stats']['total'] == 1
    assert operator.post('/api/attendance/mark',json={'session_id':sid},headers={'X-CSRF-Token':operator.csrf}).status_code == 409


def test_reset_confirmation(operator,app):
    db = app.extensions['database']
    db.insert('test-event','Camera')
    assert operator.post('/api/attendance/reset',json={},headers={'X-CSRF-Token':operator.csrf}).status_code == 400
    result = operator.post('/api/attendance/reset',json={'confirm_date':db.today().isoformat()},headers={'X-CSRF-Token':operator.csrf})
    assert result.status_code == 200 and result.json['data']['stats']['total'] == 0


def test_wrong_origin_rejected(operator):
    assert operator.post('/api/camera/select',json={'type':'webcam','index':0},headers={'X-CSRF-Token':operator.csrf,'Origin':'http://evil.example'}).status_code == 403


def test_public_network_and_rebinding_rejected(client):
    assert client.get('/dashboard',environ_overrides={'REMOTE_ADDR':'8.8.8.8'}).status_code == 403
    assert client.get('/dashboard',headers={'Host':'evil.example'}).status_code == 403


def test_camera_endpoints(operator,app):
    headers = {'X-CSRF-Token':operator.csrf}
    assert operator.get('/api/cameras').json['data']['cameras'][0]['index'] == 0
    assert operator.post('/api/camera/test',json={'type':'webcam','index':0},headers=headers).status_code == 200
    assert operator.post('/api/camera/select',json={'type':'webcam','index':0},headers=headers).status_code == 200
    assert (app.config['DATA_DIR']/'camera.enc').exists()
    assert operator.post('/api/camera/select',json={'type':'webcam','index':True},headers=headers).status_code == 400


def test_feed_mjpeg_in_memory(operator,app):
    response = operator.get('/api/camera/feed',buffered=False)
    chunk = next(response.response)
    assert b'Content-Type: image/jpeg' in chunk and b'\xff\xd8' in chunk
    response.close()
    names = [path.suffix for path in app.config['DATA_DIR'].rglob('*')]
    assert not set(names) & {'.jpg','.png','.mp4','.avi','.npy','.npz'}
    app.extensions['camera'].connected = False
    assert operator.get('/api/camera/feed').status_code == 503


def test_encrypted_credentials_and_redacted_status(tmp_path):
    source = {'type':'ip','url':'http://username:secret-password@192.168.1.100:8080/video?token=secret'}
    store = SecureStore(tmp_path)
    store.save(source)
    assert store.load() == source
    assert b'secret' not in store.path.read_bytes()
    assert 'url' not in public_source(source)
    assert '192.168' not in json.dumps(public_source(source))


@pytest.mark.parametrize('source',[{'type':'ip','url':'file:///etc/passwd'},{'type':'ip','url':'https://8.8.8.8/video'},{'type':'ip','url':'http://127.0.0.1:bad/video'},{'type':'webcam','index':-1}])
def test_invalid_camera_inputs(source):
    with pytest.raises(ValueError): validate_source(source)


def test_login_rate_limit(client):
    csrf = client.get('/api/auth/status').json['data']['csrf']
    for _ in range(8):
        assert client.post('/api/auth/login',json={'pin':'bad-pin'},headers={'X-CSRF-Token':csrf}).status_code == 401
    assert client.post('/api/auth/login',json={'pin':'bad-pin'},headers={'X-CSRF-Token':csrf}).status_code == 429


def test_model_missing_has_informative_error(app):
    from services.detection_service import FaceDetector
    config = app.config.copy(); config['MODEL_PATH'] = app.config['DATA_DIR']/'missing.pt'
    with pytest.raises(RuntimeError,match='Face model missing'): FaceDetector(config).load()


def test_bad_parameters_json_errors(client):
    for url in ['/api/attendance/stats?date=invalid','/api/attendance/events?limit=bad','/api/attendance/weekly?date=invalid']:
        response = client.get(url)
        assert response.status_code == 400 and response.json['ok'] is False


@pytest.mark.parametrize('route',['/api/auth/login','/api/attendance/mark','/api/attendance/reset'])
def test_non_object_bodies_are_rejected(operator,route):
    response = operator.post(route,json=['unexpected-array'],headers={'X-CSRF-Token':operator.csrf})
    assert response.status_code == 400 and not response.json['ok']
