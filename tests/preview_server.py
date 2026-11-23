"""Disposable visual QA only. Never used by app.py. No events in the real database.

Run with --mock for a clearly labeled synthetic video and detection fixture.
Without --mock this starts the actual camera/model stack with temporary settings.
"""
import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from services.auth import initialize_auth
from conftest import FakeCamera


class PreviewCamera(FakeCamera):
    def __init__(self):
        super().__init__()
        import cv2
        import numpy as np
        image = np.full((720,1280,3), (58,62,59),dtype=np.uint8)
        cv2.putText(image,'TEST CAMERA / SYNTHETIC INPUT',(48,675),cv2.FONT_HERSHEY_SIMPLEX,.65,(150,160,150),1,cv2.LINE_AA)
        self.jpeg = cv2.imencode('.jpg',image)[1].tobytes()

    def encoded(self):
        return self.jpeg,int(time.monotonic()*20)

    def latest(self):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock',action='store_true')
    parser.add_argument('--port',type=int,default=5055)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='attend-qa-') as directory:
        initialize_auth(Path(directory), '86420864')
        if args.mock:
            app = create_app({'DATA_DIR':Path(directory),'START_SERVICES':False},camera=PreviewCamera(),detector=SimpleNamespace(phase='ready',error=None))
            def detections():
                service = app.extensions['attendance']
                while True:
                    faces = [] if service.locked and time.monotonic()-service.recorded_at>2 else [{'box':[.41,.26,.59,.58],'confidence':.95}]
                    service.observe(faces,time.monotonic(),app.extensions['camera'].generation)
                    time.sleep(.1)
            threading.Thread(target=detections,daemon=True).start()
        else:
            app = create_app({'DATA_DIR':Path(directory)})
        print(f'Disposable QA server on http://127.0.0.1:{args.port}; operator PIN: 86420864; mock={args.mock}',flush=True)
        from waitress import serve
        try:
            serve(app,host='127.0.0.1',port=args.port,threads=16)
        finally:
            app.extensions['close']()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
