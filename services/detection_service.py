"""Face-only YOLO inference. No tracking identifiers, crops, landmarks or files."""
import threading
import time
from pathlib import Path


class FaceDetector:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.phase = "loading"
        self.error = None

    def load(self):
        path = Path(self.config["MODEL_PATH"])
        if not path.is_file():
            raise RuntimeError("Face model missing. Run .\\.venv\\Scripts\\python scripts\\download_model.py, then restart Attend.")
        from ultralytics import YOLO
        self.model = YOLO(str(path), task="detect")
        names = {str(name).strip().lower() for name in self.model.names.values()}
        if names != {"face"}:
            self.model = None
            raise RuntimeError("This model is not face-only. Install the documented yolov8n-face.pt weights.")
        self.phase = "ready"

    def detect(self, frame):
        result = self.model.predict(
            source=frame, imgsz=self.config["INFERENCE_SIZE"], conf=self.config["CONFIDENCE"],
            device=self.config["DEVICE"], verbose=False, save=False, save_txt=False,
            save_crop=False, show=False, max_det=30, stream=False,
        )[0]
        height, width = frame.shape[:2]
        return [{"box": [max(0.0, min(1.0, float(v) / dimension))
                         for v, dimension in zip(box, (width, height, width, height))],
                 "confidence": float(conf)}
                for box, conf in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist())
                if conf >= self.config["CONFIDENCE"]]


class DetectionPipeline:
    def __init__(self, config, camera, attendance, detector=None):
        self.config, self.camera, self.attendance = config, camera, attendance
        self.detector = detector or FaceDetector(config)
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="face-inference")
        self.thread.start()

    def run(self):
        try:
            self.detector.load()
        except Exception as error:
            self.detector.phase = "error"
            self.detector.error = str(error) if isinstance(error, RuntimeError) else "Face model could not load. Check the model installation and Python dependencies."
            return
        last_sequence = None
        while not self.stop.is_set():
            started = time.monotonic()
            snapshot = self.camera.latest()
            if snapshot and (snapshot[2], snapshot[3]) != last_sequence:
                frame, stamp, generation, sequence = snapshot
                last_sequence = (generation, sequence)
                try:
                    faces = self.detector.detect(frame)
                    self.attendance.observe(faces, stamp, generation)
                except Exception:
                    self.detector.phase = "error"
                    self.detector.error = "Face inference failed. Restart Attend after checking the model and available memory."
                    self.attendance.invalidate()
                    return
                finally:
                    del frame
            self.stop.wait(max(0.01, 1 / self.config["INFERENCE_FPS"] - (time.monotonic() - started)))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)
