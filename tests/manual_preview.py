"""Disposable browser QA: no real camera, records or production requests."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from conftest import FakeCamera
from werkzeug.security import generate_password_hash
from waitress import serve

if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        camera = FakeCamera()
        camera.connected = False
        app = create_app({'DATA_DIR':Path(directory),'START_SERVICES':False,'EXHIBITION_KEY':''},camera=camera,detector=SimpleNamespace(phase='error',error='No detector for this test'))
        app.config['PIN_HASH'] = generate_password_hash('test-pin-123')
        serve(app,host='127.0.0.1',port=8301)
