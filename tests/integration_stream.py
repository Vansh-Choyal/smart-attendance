r"""Opt-in real YOLO + real HTTP/MJPEG + real API integration, with disposable data.

A public OpenCV reference image is fetched/processed in memory, never saved.
The controllable test stream is NOT a physical phone or a production demo mode.
Run: .\.venv\Scripts\python tests\integration_stream.py
"""
import concurrent.futures
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import requests
from waitress import create_server

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from services.auth import initialize_auth


def main():
    reference = requests.get('https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg',timeout=30)
    reference.raise_for_status()
    image = cv2.imdecode(np.frombuffer(reference.content,dtype=np.uint8),cv2.IMREAD_COLOR)
    assert image is not None
    sample = cv2.imencode('.jpg',image)[1].tobytes()
    blank = cv2.imencode('.jpg',np.zeros_like(image))[1].tobytes()
    mode = ['face']

    class Stream(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass

        def do_GET(self):
            if mode[0] == 'offline':
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while mode[0] != 'offline':
                    frame = sample if mode[0] == 'face' else blank
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n')
                    self.wfile.flush()
                    time.sleep(.08)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                pass

    stream = ThreadingHTTPServer(('127.0.0.1',0),Stream)
    threading.Thread(target=stream.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='attend-real-integration-') as directory:
        initialize_auth(Path(directory),'86420864')
        app = create_app({'DATA_DIR':Path(directory)})
        server = create_server(app,host='127.0.0.1',port=0,threads=16)
        threading.Thread(target=server.run,daemon=True).start()
        base = f'http://127.0.0.1:{server.effective_port}'
        session = requests.Session()
        try:
            auth = session.get(base+'/api/auth/status',timeout=5).json()['data']
            login = session.post(base+'/api/auth/login',json={'pin':'86420864'},headers={'X-CSRF-Token':auth['csrf']},timeout=5).json()['data']
            headers = {'X-CSRF-Token':login['csrf']}
            configured = session.post(base+'/api/camera/test',json={'type':'ip','url':f'http://127.0.0.1:{stream.server_port}/video'},headers=headers,timeout=10)
            assert configured.status_code == 200

            def wait_for(predicate,seconds=20):
                deadline = time.monotonic()+seconds
                while time.monotonic()<deadline:
                    state = session.get(base+'/api/detection/status',timeout=5).json()['data']
                    if predicate(state):
                        return state
                    time.sleep(.15)
                raise AssertionError('Timed out waiting for state: '+str(state))

            state = wait_for(lambda state:state['ready'])
            assert state['faces_in_zone'] == 1
            token = state['session_id']
            cookies = session.cookies.get_dict()
            def mark(_):
                return requests.post(base+'/api/attendance/mark',json={'session_id':token},headers=headers,cookies=cookies,timeout=5).status_code
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                codes = list(pool.map(mark,range(16)))
            assert codes.count(201)==1 and codes.count(409)==15,codes
            print('Real YOLO + local MJPEG: stable face became READY; 16 concurrent API requests created exactly one event.',flush=True)

            mode[0] = 'blank'
            wait_for(lambda state:state['state']=='IDLE' and state['camera']['connected'])
            mode[0] = 'face'
            state = wait_for(lambda state:state['ready'])
            result = session.post(base+'/api/attendance/mark',json={'session_id':state['session_id']},headers=headers,timeout=5)
            assert result.status_code==201
            assert result.json()['data']['stats']['total']==2
            print('Clear zone + cooldown rearmed; a new eligible session created the second event.',flush=True)

            mode[0] = 'offline'
            wait_for(lambda state:not state['camera']['connected'])
            assert session.post(base+'/api/attendance/mark',json={'session_id':state['session_id']},headers=headers,timeout=5).status_code==409
            mode[0] = 'blank'
            wait_for(lambda state:state['camera']['connected'] and state['state']=='IDLE')
            assert session.get(base+'/api/attendance/stats',timeout=5).json()['data']['total']==2
            assert len(session.get(base+'/api/attendance/events',timeout=5).json()['data']['events'])==2
            assert session.get(base+'/api/attendance/weekly',timeout=5).json()['data']['days'][-1]['total']==2
            suffixes = {file.suffix.lower() for file in Path(directory).rglob('*')}
            assert not suffixes & {'.jpg','.jpeg','.png','.mp4','.avi','.npy','.npz'}
            print('Stream outage rejected marking; automatic reconnection recovered; stats/events/weekly remained consistent; no media files persisted.',flush=True)
        finally:
            mode[0] = 'offline'
            app.extensions['close']()
            server.close()
            server.task_dispatcher.shutdown(timeout=2)
            stream.shutdown()
            stream.server_close()
            session.close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
