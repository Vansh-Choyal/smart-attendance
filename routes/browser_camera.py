"""Authenticated, one-in-flight JPEG transport for browser camera capture."""
import io
import ipaddress
import secrets

from flask import Blueprint, current_app, jsonify, request, session

from services.auth import operator_required
from services.camera_service import BrowserCameraError

bp = Blueprint("browser_camera",__name__)


def body():
    value = request.get_json(silent=True)
    if not isinstance(value,dict):
        raise ValueError("Provide a JSON object.")
    return value


@bp.errorhandler(BrowserCameraError)
def camera_error(error):
    return jsonify(ok=False,error={"code":error.code,"message":error.message}),409


@bp.before_request
def secure_capture():
    if request.path.startswith('/api/camera/browser/') and not request.is_secure:
        if not ipaddress.ip_address(request.remote_addr).is_loopback:
            return jsonify(ok=False,error={"code":"https_required","message":"Open the HTTPS address to stream your phone camera."}),403


@bp.post('/api/camera/browser/start')
@operator_required
def start():
    services = current_app.extensions
    owner = session.setdefault('browser_camera_owner',secrets.token_urlsafe(32))
    with services['attendance'].lock:
        # Check competing publishers before invalidating the active detection.
        result = services['camera'].start_browser(owner)
        services['attendance'].invalidate()
        services['camera_store'].save({"type":"browser"})
        services['saved_source'] = {"type":"browser"}
    return jsonify(ok=True,data=result)


@bp.post('/api/camera/browser/renew')
@operator_required
def renew():
    return jsonify(ok=True,data=current_app.extensions['camera'].renew_browser(body().get('publisher_token')))


@bp.post('/api/camera/browser/frame')
@operator_required
def frame():
    import cv2
    import numpy as np
    from PIL import Image, UnidentifiedImageError
    camera = current_app.extensions['camera']
    request.max_content_length = current_app.config['BROWSER_FRAME_MAX_BYTES']
    token,ticket = request.headers.get('X-Camera-Session'),request.headers.get('X-Capture-Ticket')
    try:
        sequence = int(request.headers.get('X-Frame-Sequence',''))
    except ValueError:
        return jsonify(ok=False,error={"code":"invalid_frame","message":"Missing frame sequence."}),400
    camera.check_browser_frame(token,ticket,sequence)
    if request.mimetype != 'image/jpeg':
        return jsonify(ok=False,error={"code":"invalid_frame","message":"Send a JPEG camera frame."}),415
    raw = request.get_data(cache=False)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width,height = image.size
            if image.format != 'JPEG' or min(width,height)<32 or max(width,height)>1920 or width*height>2073600:
                raise ValueError('Invalid frame dimensions.')
            image.verify()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        return jsonify(ok=False,error={"code":"invalid_frame","message":"The camera frame is invalid or too large."}),400
    decoded = cv2.imdecode(np.frombuffer(raw,dtype=np.uint8),cv2.IMREAD_COLOR)
    if decoded is None:
        return jsonify(ok=False,error={"code":"invalid_frame","message":"The camera frame could not be decoded."}),400
    result = camera.publish_browser_frame(token,ticket,sequence,decoded,raw)
    return jsonify(ok=True,data=result)


@bp.post('/api/camera/browser/stop')
@operator_required
def stop():
    services = current_app.extensions
    with services['attendance'].lock:
        services['camera'].stop_browser(body().get('publisher_token'))
        services['attendance'].invalidate()
    return jsonify(ok=True,data={"stopped":True})
