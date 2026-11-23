"""Real HTTPS upload + YOLO + SQLite integration with temporary data, no browser.

Reference frames are decoded and transmitted in memory, never written to disk.
This does not verify physical phone permissions or browser certificate acceptance.
"""
import concurrent.futures
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from waitress import create_server

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from services.auth import initialize_auth
from services.local_https import https_server,ensure_certificate


def main():
    response = requests.get('https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg',timeout=30)
    response.raise_for_status()
    image = cv2.imdecode(np.frombuffer(response.content,dtype=np.uint8),cv2.IMREAD_COLOR)
    sample = cv2.imencode('.jpg',image)[1].tobytes()
    blank = cv2.imencode('.jpg',np.zeros_like(image))[1].tobytes()
    with tempfile.TemporaryDirectory(prefix='attend-browser-https-') as directory:
        initialize_auth(Path(directory),'86420864')
        app = create_app({'DATA_DIR':Path(directory),'LAN_MODE':True})
        http = create_server(app,host='127.0.0.1',port=0,threads=12)
        threading.Thread(target=http.run,daemon=True).start()
        tls = https_server(app,'127.0.0.1',0)
        tls.prepare()
        base = f'https://127.0.0.1:{tls.socket.getsockname()[1]}'
        threading.Thread(target=tls.serve,daemon=True).start()
        certificate,_ = ensure_certificate(directory)
        client = requests.Session(); client.verify = str(certificate)
        stopped = threading.Event()
        publisher = None
        try:
            assert client.get(base+'/setup',timeout=5).status_code==200
            auth = client.get(base+'/api/auth/status',timeout=5).json()['data']
            login = client.post(base+'/api/auth/login',json={'pin':'86420864'},headers={'X-CSRF-Token':auth['csrf']},timeout=5).json()['data']
            headers = {'X-CSRF-Token':login['csrf']}
            lease = client.post(base+'/api/camera/browser/start',json={},headers=headers,timeout=5).json()['data']
            token = lease['publisher_token']
            mode = ['face']; errors = []
            def publish():
                sender = requests.Session(); sender.verify = str(certificate); sender.cookies.update(client.cookies)
                ticket = lease.copy()
                try:
                    while not stopped.is_set():
                        result = sender.post(base+'/api/camera/browser/frame',data=sample if mode[0]=='face' else blank,headers={**headers,'Content-Type':'image/jpeg',
                            'X-Camera-Session':token,'X-Capture-Ticket':ticket['capture_ticket'],'X-Frame-Sequence':str(ticket['sequence'])},timeout=3)
                        if result.status_code==409 and result.json()['error']['code']=='capture_expired':
                            renewal = sender.post(base+'/api/camera/browser/renew',json={'publisher_token':token},headers=headers,timeout=3)
                            renewal.raise_for_status(); ticket = renewal.json()['data']; continue
                        result.raise_for_status(); ticket = result.json()['data']; stopped.wait(.08)
                except Exception as error:
                    errors.append(str(error))
                finally:
                    sender.close()
            publisher = threading.Thread(target=publish,daemon=True); publisher.start()
            def wait_for(predicate,seconds=25):
                deadline = time.monotonic()+seconds
                while time.monotonic()<deadline:
                    state = client.get(base+'/api/detection/status',timeout=5).json()['data']
                    if predicate(state): return state
                    if errors: raise AssertionError(errors)
                    time.sleep(.12)
                raise AssertionError('State timeout: '+str(state))
            state = wait_for(lambda state:state['ready'])
            assert state['camera']['source']['type']=='browser'
            print('HTTPS certificate verified; browser-upload JPEG transport reached READY through the real YOLO detector.',flush=True)
            cookies = client.cookies.get_dict()
            def mark(_):
                return requests.post(base+'/api/attendance/mark',json={'session_id':state['session_id']},headers=headers,cookies=cookies,verify=str(certificate),timeout=5).status_code
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: codes = list(pool.map(mark,range(16)))
            assert codes.count(201)==1 and codes.count(409)==15,codes
            mode[0] = 'blank'
            wait_for(lambda state:state['state']=='IDLE')
            mode[0] = 'face'
            state = wait_for(lambda state:state['ready'])
            marked = client.post(base+'/api/attendance/mark',json={'session_id':state['session_id']},headers=headers,timeout=5)
            assert marked.status_code==201 and marked.json()['data']['stats']['total']==2
            print('16 concurrent HTTPS marks created one event; clear-zone/cooldown rearming permitted the next event.',flush=True)
            stopped.set(); publisher.join(timeout=5)
            wait_for(lambda state:not state['camera']['connected'])
            assert client.post(base+'/api/attendance/mark',json={'session_id':state['session_id']},headers=headers,timeout=5).status_code==409
            http_data = requests.get(f'http://127.0.0.1:{http.effective_port}/api/attendance/stats',timeout=5).json()['data']
            assert http_data['total']==2
            assert not any(file.suffix.lower() in {'.jpg','.jpeg','.png','.mp4','.npy','.npz'} for file in Path(directory).rglob('*'))
            print('Upload loss invalidated marking; HTTP and HTTPS shared the same count; no frames persisted.',flush=True)
        finally:
            stopped.set()
            if publisher: publisher.join(timeout=5)
            app.extensions['close'](); client.close(); tls.stop()
            http.close(); http.task_dispatcher.shutdown(timeout=2)


if __name__=='__main__':
    main()
