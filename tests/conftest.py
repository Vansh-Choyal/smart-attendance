import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from werkzeug.security import generate_password_hash

from app import create_app


class FakeCamera:
    def __init__(self):
        self.lock = threading.RLock()
        self.source = {"type": "webcam", "index": 0}
        self.connected = True
        self.generation = 1
        self.frame_time = time.monotonic()

    def status(self):
        return {"connected": self.connected, "phase": "connected" if self.connected else "disconnected",
                "source": {"type":"webcam", "index":0, "label":"Built-in camera · 0"},
                "generation":self.generation,"width":640,"height":480,"retry":0,"retry_in":0}

    def select(self, source):
        self.source = source
        self.generation += 1

    def cameras(self):
        return [{"index":0,"label":"Camera 0"}]

    def latest(self):
        return np.zeros((480,640,3), dtype=np.uint8), self.frame_time, self.generation, 1

    def encoded(self):
        import cv2
        return cv2.imencode('.jpg',np.zeros((32,32,3),dtype=np.uint8))[1].tobytes(), 1

    def close(self):
        pass


@pytest.fixture
def app(tmp_path):
    camera = FakeCamera()
    model = SimpleNamespace(phase="ready",error=None)
    app = create_app({"TESTING":True,"START_SERVICES":False,"DATA_DIR":tmp_path}, camera=camera, detector=model)
    app.config["PIN_HASH"] = generate_password_hash("12345678")
    yield app
    app.extensions["close"]()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def operator(client):
    auth = client.get('/api/auth/status').json['data']
    result = client.post('/api/auth/login',json={"pin":"12345678"},headers={"X-CSRF-Token":auth['csrf']})
    client.csrf = result.json['data']['csrf']
    return client


@pytest.fixture
def face():
    return {"box":[.4,.25,.6,.6],"confidence":.95}


def ready(app, face):
    service = app.extensions['attendance']
    for offset in [.5, .3, .1, 0]:
        # Real clock for API tests, deterministic clock for state-machine tests.
        stamp = time.monotonic()
        if offset == .5:
            service.observe([face],stamp,app.extensions['camera'].generation)
            service.stable_since -= .5
        else:
            service.observe([face],stamp,app.extensions['camera'].generation)
    return service.snapshot()['session_id']
