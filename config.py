"""All timing, camera and inference controls live here (or ATTEND_* environment variables)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Config:
    DATA_DIR = Path(os.getenv("ATTEND_DATA_DIR", ROOT / "data"))
    MODEL_PATH = Path(os.getenv("ATTEND_MODEL_PATH", ROOT / "models" / "yolov8n-face.pt"))
    TIMEZONE = os.getenv("ATTEND_TIMEZONE", "Asia/Kolkata")
    CONFIDENCE = float(os.getenv("ATTEND_CONFIDENCE", "0.6"))
    INFERENCE_SIZE = int(os.getenv("ATTEND_INFERENCE_SIZE", "640"))
    INFERENCE_FPS = float(os.getenv("ATTEND_INFERENCE_FPS", "8"))
    DEVICE = os.getenv("ATTEND_DEVICE", "cpu")
    STABLE_SECONDS = float(os.getenv("ATTEND_STABLE_SECONDS", "0.4"))
    CLEAR_SECONDS = float(os.getenv("ATTEND_CLEAR_SECONDS", "1.0"))
    COOLDOWN_SECONDS = float(os.getenv("ATTEND_COOLDOWN_SECONDS", "2.0"))
    DETECTION_MAX_AGE = float(os.getenv("ATTEND_DETECTION_MAX_AGE", "1.0"))
    CAMERA_MAX_AGE = float(os.getenv("ATTEND_CAMERA_MAX_AGE", "1.5"))
    ZONE = tuple(float(v) for v in os.getenv("ATTEND_ZONE", "0.24,0.20,0.76,0.80").split(","))
    CAMERA_WIDTH = int(os.getenv("ATTEND_CAMERA_WIDTH", "1280"))
    CAMERA_HEIGHT = int(os.getenv("ATTEND_CAMERA_HEIGHT", "720"))
    PREVIEW_FPS = int(os.getenv("ATTEND_PREVIEW_FPS", "20"))
    CAMERA_SCAN_LIMIT = int(os.getenv("ATTEND_CAMERA_SCAN_LIMIT", "4"))
    BROWSER_UPLOAD_FPS = int(os.getenv("ATTEND_BROWSER_UPLOAD_FPS", "12"))
    BROWSER_FRAME_MAX_BYTES = 2 * 1024 * 1024
    HTTPS_PORT = 5443
    LAN_MODE = False
    START_SERVICES = True
    TESTING = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    MAX_CONTENT_LENGTH = 8192
