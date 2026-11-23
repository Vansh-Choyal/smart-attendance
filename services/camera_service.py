"""One capture process, one latest-frame slot, shared in-memory JPEG for all viewers.

OpenCV network backends can block despite their timeout settings. Isolating capture
lets source changes and shutdown terminate that backend within a bounded interval.
"""
import ipaddress
import multiprocessing as mp
import os
import queue
import secrets
import hmac
import socket
import threading
import time
from urllib.parse import urlsplit, urlunsplit


def validate_source(payload):
    kind = payload.get("type")
    if kind == "browser":
        return {"type": "browser"}
    if kind == "webcam":
        index = payload.get("index", 0)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 20:
            raise ValueError("Camera index must be a number between 0 and 20.")
        return {"type": "webcam", "index": index}
    if kind != "ip":
        raise ValueError("Choose a built-in, browser or IP camera.")
    raw = payload.get("url", "")
    if not isinstance(raw, str) or len(raw) > 2048 or any(ord(c) < 32 for c in raw):
        raise ValueError("Enter a valid local camera stream URL.")
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https", "rtsp"} or not parts.hostname or parts.fragment:
        raise ValueError("Use an HTTP, HTTPS or RTSP camera URL without a fragment.")
    try:
        port = parts.port
        addresses = socket.getaddrinfo(parts.hostname, port or 80, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        raise ValueError("The camera hostname or port could not be resolved.") from None
    if not addresses or any(not (ipaddress.ip_address(a[4][0]).is_private or ipaddress.ip_address(a[4][0]).is_loopback)
                            or ipaddress.ip_address(a[4][0]).is_unspecified or ipaddress.ip_address(a[4][0]).is_multicast
                            for a in addresses):
        raise ValueError("Only cameras on your local network are supported.")
    return {"type": "ip", "url": urlunsplit(parts)}


def public_source(source):
    # Do not send any portion of a credential-bearing URL to viewers or logs.
    if not source:
        return None
    if source["type"] == "browser":
        return {"type": "browser", "label": "Phone browser camera"}
    if source["type"] == "webcam":
        return {"type": "webcam", "index": source["index"], "label": f"Built-in camera · {source['index']}"}
    return {"type": "ip", "label": "IP camera", "configured": True}


def source_label(source):
    public = public_source(source)
    return public["label"] if public else "No camera"


def _latest_put(out, value):
    try:
        out.put_nowait(value)
    except queue.Full:
        try:
            out.get_nowait()
        except queue.Empty:
            pass
        try:
            out.put_nowait(value)
        except queue.Full:
            pass


def _open_capture(source, width, height):
    import cv2
    if source["type"] == "webcam":
        cap = cv2.VideoCapture(source["index"], cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        cap = cv2.VideoCapture(source["url"], cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000,
        ])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def _capture_worker(source, frames, statuses, stop, width, height):
    # Native FFmpeg messages can include credentials. Never relay or log them.
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, 2)
        os.close(null_fd)
    except OSError:
        pass
    import cv2
    cv2.setLogLevel(0)
    # Supervise native open/read calls too: some device drivers ignore timeouts.
    progress = [time.monotonic()]
    def watchdog():
        while not stop.wait(1):
            if time.monotonic() - progress[0] > 12:
                os._exit(3)
    threading.Thread(target=watchdog, daemon=True).start()
    retry = 0
    epoch = 0
    while not stop.is_set():
        cap = None
        try:
            progress[0] = time.monotonic()
            _latest_put(statuses, {"phase": "connecting", "retry": retry, "changed_at":time.monotonic()})
            cap = _open_capture(source, width, height)
            if not cap.isOpened():
                raise RuntimeError("unavailable")
            epoch += 1
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError("disconnected")
                retry = 0
                progress[0] = time.monotonic()
                _latest_put(frames, (frame, time.monotonic(), epoch))
        except Exception:
            retry += 1
            delay = min(2 ** min(retry - 1, 4), 16)
            _latest_put(statuses, {"phase": "disconnected", "retry": retry, "retry_in": delay, "changed_at":time.monotonic()})
            for _ in range(delay):
                progress[0] = time.monotonic()
                if stop.wait(1):
                    break
        finally:
            if cap is not None:
                cap.release()


def _probe_worker(limit, output):
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, 2)
        os.close(null_fd)
    except OSError:
        pass
    found = []
    for index in range(limit):
        cap = None
        try:
            cap = _open_capture({"type": "webcam", "index": index}, 640, 480)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    found.append({"index": index, "label": f"Camera {index}"})
        finally:
            if cap is not None:
                cap.release()
    output.put(found)


class CameraService:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.change_lock = threading.Lock()
        self.probe_lock = threading.Lock()
        self.context = mp.get_context("spawn")
        self.source = None
        self.generation = 0
        self.frame = None
        self.frame_time = 0
        self.sequence = 0
        self.jpeg = None
        self.phase = "unconfigured"
        self.retry = 0
        self.retry_in = 0
        self.process = None
        self.stop_event = None
        self.reader_stop = None
        self.reader = None
        self.frames = None
        self.statuses = None
        self.epoch = None
        self.scan_cache = None
        self.scan_time = 0
        self.browser_token = None
        self.browser_owner = None
        self.browser_ticket = None
        self.browser_ticket_time = 0
        self.browser_sequence = 0

    def _stop_current(self):
        if self.stop_event:
            self.stop_event.set()
        if self.reader_stop:
            self.reader_stop.set()
        if self.reader:
            self.reader.join(timeout=1)
        if self.process and self.process.pid is not None:
            self.process.join(timeout=0.8)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
        for channel in (self.frames, self.statuses):
            if channel:
                channel.cancel_join_thread()
                channel.close()
        self.process = self.reader = self.stop_event = self.reader_stop = None
        self.frames = self.statuses = None

    def select(self, source):
        with self.change_lock:
            with self.lock:
                self.generation += 1
                self.frame = self.jpeg = None
                self.frame_time = 0
                self.phase = "connecting"
                self.source = source.copy()
                self.epoch = None
                self.retry = self.retry_in = 0
                self.browser_token = self.browser_owner = self.browser_ticket = None
            self._stop_current()
            with self.lock:
                self.frame = self.jpeg = None
                self.frame_time = 0
                self.phase = "connecting"
                if source["type"] == "browser":
                    self.phase = "awaiting_browser"
                    return
            self.frames = self.context.Queue(maxsize=1)
            self.statuses = self.context.Queue(maxsize=16)
            self.stop_event = self.context.Event()
            self.reader_stop = threading.Event()
            self.process = self.context.Process(target=_capture_worker, args=(
                source, self.frames, self.statuses, self.stop_event,
                self.config["CAMERA_WIDTH"], self.config["CAMERA_HEIGHT"],
            ), daemon=True)
            self.process.start()
            self.reader = threading.Thread(target=self._read, args=(self.reader_stop,), daemon=True, name="camera-latest")
            self.reader.start()

    def start_browser(self, owner):
        with self.lock:
            if (self.source and self.source["type"] == "browser" and self.browser_token
                    and self.browser_owner != owner and time.monotonic()-max(self.frame_time,self.browser_ticket_time) < 10):
                raise BrowserCameraError("Another phone is streaming. Stop it before connecting this phone.", "publisher_busy")
        self.select({"type":"browser"})
        with self.lock:
            self.browser_token, self.browser_owner = secrets.token_urlsafe(32), owner
            self.browser_sequence = 0
            return {"publisher_token":self.browser_token, **self._new_ticket()}

    def _new_ticket(self):
        self.browser_ticket = secrets.token_urlsafe(24)
        self.browser_ticket_time = time.monotonic()
        return {"capture_ticket":self.browser_ticket, "sequence":self.browser_sequence+1,
                "fps":self.config["BROWSER_UPLOAD_FPS"]}

    def _check_browser(self, token):
        if (not self.source or self.source["type"] != "browser" or not self.browser_token
                or not isinstance(token,str) or not hmac.compare_digest(token,self.browser_token)):
            raise BrowserCameraError("This camera session ended. Connect this phone again.", "publisher_changed")

    def renew_browser(self, token):
        with self.lock:
            self._check_browser(token)
            return self._new_ticket()

    def check_browser_frame(self, token, ticket, sequence):
        with self.lock:
            self._check_browser(token)
            if (not isinstance(ticket,str) or not self.browser_ticket or not hmac.compare_digest(ticket,self.browser_ticket)
                    or time.monotonic()-self.browser_ticket_time > self.config["DETECTION_MAX_AGE"]):
                raise BrowserCameraError("The frame expired. Request a fresh capture ticket.", "capture_expired")
            if sequence != self.browser_sequence+1:
                raise BrowserCameraError("An outdated camera frame was rejected.", "frame_out_of_order")

    def publish_browser_frame(self, token, ticket, sequence, frame, jpeg):
        with self.lock:
            self.check_browser_frame(token,ticket,sequence)
            stamp = self.browser_ticket_time
            if not self.status()["connected"]:
                self.generation += 1
            self.frame,self.jpeg,self.frame_time = frame,jpeg,stamp
            self.phase,self.retry,self.retry_in = "connected",0,0
            self.sequence += 1
            self.browser_sequence = sequence
            return self._new_ticket()

    def stop_browser(self, token):
        with self.lock:
            self._check_browser(token)
            self.browser_token = self.browser_owner = self.browser_ticket = None
            self.phase = "awaiting_browser"
            self.frame = self.jpeg = None
            self.frame_time = 0
            self.generation += 1

    def _read(self, stopped):
        import cv2
        last_jpeg = 0
        invalid_before = 0
        while not stopped.is_set():
            try:
                while True:
                    message = self.statuses.get_nowait()
                    with self.lock:
                        self.phase = message["phase"]
                        self.retry = max(self.retry,message.get("retry", 0))
                        self.retry_in = message.get("retry_in", 0)
                        if self.phase != "connected":
                            invalid_before = max(invalid_before,message["changed_at"])
                            self.frame = self.jpeg = None
                            self.frame_time = 0
            except (queue.Empty,EOFError,OSError,ValueError):
                pass
            try:
                frame, stamp, epoch = self.frames.get(timeout=0.1)
            except (queue.Empty,EOFError,OSError,ValueError):
                if not self.process.is_alive() and not stopped.is_set():
                    # A native camera call stalled or the worker crashed. Start a
                    # fresh channel/process, never reuse a possibly broken pipe.
                    with self.lock:
                        self.phase = "disconnected"
                        self.frame = self.jpeg = None
                        self.frame_time = 0
                        self.generation += 1
                        self.retry += 1
                        self.retry_in = min(2 ** min(self.retry-1,4),16)
                    if stopped.wait(self.retry_in):
                        return
                    self.process.join(timeout=0.2)
                    for channel in (self.frames,self.statuses):
                        channel.cancel_join_thread()
                        channel.close()
                    self.frames = self.context.Queue(maxsize=1)
                    self.statuses = self.context.Queue(maxsize=16)
                    next_process = self.context.Process(target=_capture_worker,args=(
                        self.source,self.frames,self.statuses,self.stop_event,
                        self.config["CAMERA_WIDTH"],self.config["CAMERA_HEIGHT"],
                    ),daemon=True)
                    if stopped.is_set():
                        return
                    self.process = next_process
                    self.process.start()
                continue
            if stopped.is_set() or stamp <= invalid_before or time.monotonic() - stamp > self.config["CAMERA_MAX_AGE"]:
                continue
            with self.lock:
                if epoch != self.epoch:
                    self.epoch = epoch
                    self.generation += 1
                self.frame, self.frame_time = frame, stamp
                self.sequence += 1
                self.phase, self.retry, self.retry_in = "connected", 0, 0
            if time.monotonic() - last_jpeg >= 1 / self.config["PREVIEW_FPS"]:
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    with self.lock:
                        self.jpeg = encoded.tobytes()
                    last_jpeg = time.monotonic()

    def status(self):
        with self.lock:
            fresh = self.phase == "connected" and time.monotonic() - self.frame_time <= self.config["CAMERA_MAX_AGE"]
            phase = "disconnected" if self.phase == "connected" and not fresh else self.phase
            return {"connected": fresh, "phase": phase, "source": public_source(self.source),
                    "generation": self.generation, "retry": self.retry, "retry_in": self.retry_in,
                    "width": int(self.frame.shape[1]) if fresh else 0,
                    "height": int(self.frame.shape[0]) if fresh else 0}

    def latest(self):
        with self.lock:
            if not self.status()["connected"]:
                return None
            return self.frame.copy(), self.frame_time, self.generation, self.sequence

    def encoded(self):
        with self.lock:
            return (self.jpeg, self.sequence) if self.status()["connected"] else (None, self.sequence)

    def cameras(self):
        with self.probe_lock:
            if self.scan_cache is not None and time.monotonic() - self.scan_time < 30:
                return self.scan_cache
            active = self.status()
            # Reopening an active webcam for a scan can steal its device handle.
            if active["source"] and active["source"]["type"] == "webcam":
                return [{"index": active["source"]["index"], "label": active["source"]["label"]}]
            output = self.context.Queue(maxsize=1)
            worker = self.context.Process(target=_probe_worker, args=(self.config["CAMERA_SCAN_LIMIT"], output), daemon=True)
            worker.start()
            try:
                result = output.get(timeout=7)
            except queue.Empty:
                result = []
            finally:
                worker.join(timeout=0.3)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=1)
                output.cancel_join_thread()
                output.close()
            self.scan_cache, self.scan_time = result, time.monotonic()
            return result

    def close(self):
        with self.change_lock:
            with self.lock:
                self.phase = "disconnected"
                self.frame = self.jpeg = None
                self.frame_time = 0
                self.generation += 1
                self.browser_token = self.browser_owner = self.browser_ticket = None
            self._stop_current()


class BrowserCameraError(Exception):
    def __init__(self,message,code):
        self.message,self.code = message,code
