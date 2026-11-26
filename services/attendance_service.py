"""Geometric session state, serialized with marking and source changes.

The lockout tracks continuous occupancy of the zone, never personal identity.
"""
import sqlite3
import threading
import time
import uuid

from services.camera_service import source_label


class AttendanceError(Exception):
    def __init__(self, message, code="not_ready", status=409):
        self.message, self.code, self.status = message, code, status


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0]) * (a[3]-a[1]) + (b[2]-b[0]) * (b[3]-b[1]) - intersection
    return intersection / union if union else 0


class AttendanceService:
    def __init__(self, config, camera, database, clock=time.monotonic):
        self.config, self.camera, self.database, self.clock = config, camera, database, clock
        self.lock = threading.RLock()
        self.state = "CAMERA_DISCONNECTED"
        self.faces = []
        self.eligible = []
        self.last_observation = 0
        self.generation = None
        self.stable_since = None
        self.clear_since = None
        self.session_id = None
        self.recorded_at = None
        self.locked = False
        self.last_box = None
        self.detector = None

    def invalidate(self):
        with self.lock:
            self.faces, self.eligible = [], []
            self.stable_since = self.clear_since = self.session_id = self.last_box = None
            self.last_observation = 0
            self.state = "CAMERA_DISCONNECTED"
            # A connection failure is not evidence of an empty zone.

    def _inside(self, box):
        left, top, right, bottom = self.config["ZONE"]
        center_x, center_y = (box[0]+box[2])/2, (box[1]+box[3])/2
        return left <= center_x <= right and top <= center_y <= bottom

    def observe(self, faces, frame_time, generation):
        with self.lock, self.camera.lock:
            now = self.clock()
            status = self.camera.status()
            if (not status["connected"] or status["generation"] != generation
                    or now - frame_time > self.config["DETECTION_MAX_AGE"]):
                self.invalidate()
                return
            if generation != self.generation or now - self.last_observation > self.config["DETECTION_MAX_AGE"]:
                self.invalidate()
            self.generation = generation
            self.last_observation = frame_time
            self.faces = [face for face in faces if face["confidence"] >= self.config["CONFIDENCE"]]
            self.eligible = [face for face in self.faces if self._inside(face["box"])]
            if self.locked:
                self.state = "RECORDED" if now - self.recorded_at < 0.65 else "WAITING_FOR_CLEAR"
                if self.eligible:
                    self.clear_since = None
                else:
                    if self.clear_since is None:
                        self.clear_since = now
                    if (now - self.clear_since >= self.config["CLEAR_SECONDS"]
                            and now - self.recorded_at >= self.config["COOLDOWN_SECONDS"]):
                        self.locked = False
                        self.session_id = self.clear_since = self.stable_since = self.last_box = None
                        self.state = "IDLE"
                return
            if len(self.eligible) != 1:
                self.stable_since = self.session_id = self.last_box = None
                self.state = "FACE_DETECTED" if self.eligible else "IDLE"
                return
            box = self.eligible[0]["box"]
            if self.stable_since is None or (self.last_box and overlap(box, self.last_box) < 0.2):
                self.stable_since = now
                self.session_id = uuid.uuid4().hex
            self.last_box = box
            self.state = "READY" if now - self.stable_since >= self.config["STABLE_SECONDS"] else "FACE_DETECTED"

    def snapshot(self):
        with self.lock, self.camera.lock:
            now = self.clock()
            camera = self.camera.status()
            model_phase = self.detector.phase if self.detector else "loading"
            model_error = self.detector.error if self.detector else None
            fresh = camera["connected"] and self.generation == camera["generation"] and now - self.last_observation <= self.config["DETECTION_MAX_AGE"]
            if not fresh or model_phase != "ready":
                self.invalidate()
            if not camera["source"]:
                message = "Choose a camera to begin"
            elif not camera["connected"]:
                message = "Connect your phone browser" if camera["phase"] == "awaiting_browser" else "Camera disconnected" if camera["phase"] != "connecting" else "Connecting to camera"
            elif model_phase == "error":
                message = "Face detector unavailable"
            elif model_phase != "ready":
                message = "Loading face detector"
            elif not fresh:
                message = "Waiting for fresh detection"
            elif self.locked:
                message = "Attendance recorded" if self.state == "RECORDED" else "Waiting for zone to clear"
            elif len(self.eligible) > 1:
                message = "Multiple faces detected — isolate one person"
            elif self.state == "READY":
                message = "Face detected"
            elif self.eligible:
                message = "Hold still for a moment"
            elif self.faces:
                message = "Move into detection zone"
            else:
                message = "Waiting for face"
            return {"state": self.state, "message": message, "ready": self.state == "READY" and fresh and model_phase == "ready",
                    "faces_in_zone": len(self.eligible), "face_count": len(self.faces),
                    "faces": self.faces if fresh else [], "zone": self.config["ZONE"],
                    "session_id": self.session_id if self.state == "READY" else None,
                    "model": {"phase": model_phase, "error": model_error}, "camera": camera,
                    "cooldown_remaining": max(0, self.config["COOLDOWN_SECONDS"]-(now-self.recorded_at)) if self.locked else 0}

    def mark(self, requested_session=None):
        with self.lock, self.camera.lock:
            # One operator click is one entry, independent of camera/model state.
            # A caller-generated request ID makes network retries idempotent.
            event_id = requested_session or str(uuid.uuid4())
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
                raise AttendanceError('Invalid attendance request ID.', 'invalid_request', 400)
            try:
                event = self.database.insert(event_id, source_label(self.camera.source) if self.camera.source else 'Manual entry')
            except sqlite3.IntegrityError:
                self.locked, self.recorded_at, self.state = True, self.clock(), "RECORDED"
                raise AttendanceError("Attendance has already been recorded for this session.", "already_recorded") from None
            return {"event": event, "stats": self.database.stats(), "detection": self.snapshot()}
