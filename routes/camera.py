import time

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from services.auth import operator_required
from services.camera_service import validate_source

bp = Blueprint("camera_api", __name__)


@bp.get("/api/cameras")
@operator_required
def cameras():
    camera = current_app.extensions["camera"]
    return jsonify(ok=True, data={"cameras": camera.cameras(), "scan_limit": current_app.config["CAMERA_SCAN_LIMIT"]})


def choose(persist):
    services = current_app.extensions
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error={"code": "invalid_source", "message": "Provide a camera source."}), 400
    try:
        if payload.get("use_saved"):
            source = services["camera_store"].load()
            if not source:
                raise ValueError("No saved camera is available. Enter a stream URL or camera index.")
            source = validate_source(source)
        else:
            source = validate_source(payload)
        with services["attendance"].lock:
            if source != services["camera"].source or not services["camera"].status()["connected"]:
                services["attendance"].invalidate()
                services["camera"].select(source)
            if persist:
                services["camera_store"].save(source)
                services["saved_source"] = source
    except ValueError as error:
        return jsonify(ok=False, error={"code": "invalid_source", "message": str(error)}), 400
    except Exception:
        return jsonify(ok=False, error={"code": "camera_error", "message": "The camera configuration could not be opened or saved. Check local file access and try again."}), 500
    return jsonify(ok=True, data={"camera": services["camera"].status(), "saved": persist,
                                  "message": "Camera saved. Connecting…" if persist else "Testing camera. Watch the live preview for connection status."})


@bp.post("/api/camera/test")
@operator_required
def test_camera():
    # Testing switches the single active source. A successful first frame proves connection.
    return choose(False)


@bp.post("/api/camera/select")
@operator_required
def select_camera():
    return choose(True)


@bp.get("/api/camera/status")
def camera_status():
    from services.camera_service import public_source
    return jsonify(ok=True, data=current_app.extensions["camera"].status() | {
        "saved_source": public_source(current_app.extensions.get("saved_source")),
        "configuration_error": current_app.extensions.get("configuration_error"),
    })


@bp.get("/api/camera/feed")
@operator_required
def feed():
    camera = current_app.extensions["camera"]
    if not camera.status()["connected"]:
        return jsonify(ok=False, error={"code": "camera_disconnected", "message": "No live camera frame is available."}), 503
    fps = current_app.config["PREVIEW_FPS"]

    @stream_with_context
    def frames():
        last = -1
        # Reconnect periodically to revalidate the operator's cookie/session.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            jpeg, sequence = camera.encoded()
            if jpeg is None:
                return
            if last != sequence:
                last = sequence
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(1/fps)
    return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@bp.get("/api/detection/status")
def detection_status():
    from flask import session
    state = current_app.extensions["attendance"].snapshot()
    if not session.get("operator"):
        state["faces"] = []
        state["session_id"] = None
        state["ready"] = False
    return jsonify(ok=True, data=state)
