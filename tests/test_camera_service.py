import queue
import threading
import time
from types import SimpleNamespace

import numpy as np

from services.camera_service import CameraService


def test_queued_frame_before_disconnect_cannot_reconnect(app):
    camera = CameraService(app.config)
    camera.frames = queue.Queue()
    camera.statuses = queue.Queue()
    camera.source = {'type':'webcam','index':0}
    camera.process = SimpleNamespace(is_alive=lambda: True)
    now = time.monotonic()
    camera.frames.put((np.zeros((32,32,3),dtype=np.uint8),now-.01,1))
    camera.statuses.put({'phase':'disconnected','retry':1,'retry_in':1,'changed_at':now})
    stopped = threading.Event()
    reader = threading.Thread(target=camera._read,args=(stopped,))
    reader.start()
    time.sleep(.15)
    stopped.set(); reader.join(timeout=1)
    assert not reader.is_alive()
    assert camera.frame is None and camera.jpeg is None
    assert not camera.status()['connected']


def test_capture_freshness_expires_independent_of_model(app):
    camera = CameraService(app.config)
    camera.source = {'type':'webcam','index':0}
    camera.phase = 'connected'
    camera.frame = np.zeros((32,32,3),dtype=np.uint8)
    camera.frame_time = time.monotonic()-2
    camera.jpeg = b'not-servable'
    assert camera.status()['phase'] == 'disconnected'
    assert camera.latest() is None
    assert camera.encoded()[0] is None


def test_old_camera_generation_cannot_publish_eligible_result(app,face):
    service,camera = app.extensions['attendance'],app.extensions['camera']
    camera.generation = 2
    service.observe([face],time.monotonic(),1)
    assert not service.snapshot()['ready']
    assert service.last_observation == 0
