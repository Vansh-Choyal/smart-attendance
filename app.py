import argparse
import atexit
import getpass
import multiprocessing
import secrets
import threading
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.exceptions import HTTPException

from config import Config
from database.db import Database
from routes.attendance import bp as attendance_bp
from routes.camera import bp as camera_bp
from routes.browser_camera import bp as browser_camera_bp
from services.attendance_service import AttendanceService
from services.auth import AuthGuard, initialize_auth
from services.camera_service import CameraService, validate_source
from services.detection_service import DetectionPipeline
from services.secure_store import SecureStore
from services.exhibition_sync import ExhibitionSync


def create_app(overrides=None, camera=None, detector=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(overrides or {})
    cfg = app.config
    zone = cfg["ZONE"]
    if len(zone) != 4 or not (0 <= zone[0] < zone[2] <= 1 and 0 <= zone[1] < zone[3] <= 1):
        raise ValueError("ATTEND_ZONE must contain normalized left,top,right,bottom coordinates.")
    for key in ("INFERENCE_FPS", "STABLE_SECONDS", "CLEAR_SECONDS", "COOLDOWN_SECONDS", "DETECTION_MAX_AGE", "CAMERA_MAX_AGE", "PREVIEW_FPS", "BROWSER_UPLOAD_FPS"):
        if cfg[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if not 0 < cfg["CONFIDENCE"] <= 1:
        raise ValueError("CONFIDENCE must be between 0 and 1.")
    directory = Path(cfg["DATA_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    secret, pin_hash = initialize_auth(directory)
    cfg["SECRET_KEY"], cfg["PIN_HASH"] = secret, pin_hash
    db = Database(directory / "attendance.sqlite3", cfg["TIMEZONE"])
    sync = ExhibitionSync(cfg, db)
    app.extensions['exhibition_sync'] = sync
    camera = camera or CameraService(cfg)
    attendance = AttendanceService(cfg, camera, db)
    pipeline = DetectionPipeline(cfg, camera, attendance, detector)
    attendance.detector = pipeline.detector
    store = SecureStore(directory)
    app.extensions.update(database=db, camera=camera, attendance=attendance, pipeline=pipeline, camera_store=store)
    guard = AuthGuard(app)
    app.register_blueprint(camera_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(browser_camera_bp)

    @app.context_processor
    def context():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf"], "operator": bool(session.get("operator")), "timezone_name": cfg["TIMEZONE"], "today_label":db.today().strftime("%a, %d %b"), "https_port":cfg['HTTPS_PORT']}

    @app.get("/")
    def index():
        return redirect("/dashboard" if app.extensions.get("saved_source") else "/setup")

    @app.get("/setup")
    def setup():
        return render_template("setup.html", page="setup", title="Camera setup")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html", page="dashboard", title="Attendance overview", today=db.today().isoformat())

    @app.get("/camera")
    def camera_page():
        return render_template("camera.html", page="camera", title="Live camera")

    @app.get("/api/auth/status")
    def auth_status():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        return jsonify(ok=True, data={"operator": bool(session.get("operator")), "csrf": session["csrf"], "timezone": cfg["TIMEZONE"]})

    @app.get('/api/exhibition/status')
    def exhibition_status():
        return jsonify(ok=True, data=sync.status())

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload,dict):
            return jsonify(ok=False,error={"code":"invalid_body","message":"Provide a JSON object."}),400
        valid, limited = guard.login(payload.get("pin"))
        if limited:
            return jsonify(ok=False, error={"code": "rate_limited", "message": "Too many attempts. Wait one minute and try again."}), 429
        if not valid:
            return jsonify(ok=False, error={"code": "invalid_pin", "message": "That operator PIN is incorrect."}), 401
        return jsonify(ok=True, data={"operator": True, "csrf": session["csrf"]})

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(ok=True, data={"operator": False, "csrf": session["csrf"]})

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store" if not request.path.startswith("/static/") else "public, max-age=3600"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.errorhandler(Exception)
    def handle_error(error):
        status = error.code if isinstance(error, HTTPException) else 400 if isinstance(error, (ValueError, TypeError, OverflowError)) else 500
        message = "Invalid request parameters." if status == 400 else "Request not found." if status == 404 else "The request could not be completed. Try again."
        if status == 500:
            app.logger.error("Request failed (%s)", type(error).__name__)
        return jsonify(ok=False, error={"code": f"http_{status}", "message": message}), status

    def close():
        sync.close()
        pipeline.close()
        camera.close()
    app.extensions["close"] = close
    if cfg["START_SERVICES"]:
        try:
            saved = store.load()
            app.extensions["saved_source"] = saved
            if saved:
                camera.select(validate_source(saved))
        except Exception:
            app.extensions["configuration_error"] = "Saved camera could not be opened. Reconnect it in Setup."
        pipeline.start()
        sync.start()
        atexit.register(close)
    return app


def main():
    parser = argparse.ArgumentParser(description="Attend. Local attendance, confirmed by an operator.")
    parser.add_argument("--lan", action=argparse.BooleanOptionalAction, default=True, help="Allow private-network access (default); use --no-lan for this computer only")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--https-port",type=int,default=5443,help="HTTPS port for direct phone browser cameras in LAN mode")
    parser.add_argument("--no-https",action="store_true",help="Disable the local HTTPS listener (phone browser capture will require another HTTPS origin)")
    parser.add_argument("--set-pin", action="store_true", help="Change the operator PIN without starting the server")
    args = parser.parse_args()
    if args.set_pin:
        directory = Path(Config.DATA_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        pin = getpass.getpass("New operator PIN or passphrase (6+ characters): ")
        if pin != getpass.getpass("Repeat PIN: "):
            raise SystemExit("PINs did not match.")
        initialize_auth(directory, pin)
        # Changing PIN invalidates existing signed operator sessions.
        from services.secure_store import atomic_write
        atomic_write(directory / "session.key", secrets.token_bytes(32))
        print("Operator PIN updated. Restart Attend if it is running.")
        return
    use_https = args.lan and not args.no_https
    if use_https and args.https_port == args.port:
        parser.error("HTTP and HTTPS need different ports.")
    app = create_app({"LAN_MODE": args.lan,"HTTPS_PORT":args.https_port if use_https else 0})
    from waitress import create_server
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    http = tls = None
    print(f"Attend. is listening on {host}:{args.port}. Open http://127.0.0.1:{args.port}/setup on this computer.", flush=True)
    if args.lan:
        print("LAN mode enabled. Use this laptop's private IPv4 address on trusted Wi-Fi. Do not port-forward.", flush=True)
    try:
        http = create_server(app,host=host,port=args.port,threads=24,clear_untrusted_proxy_headers=True)
        if use_https:
            from services.local_https import https_server,local_addresses
            tls = https_server(app,host,args.https_port)
            for address in local_addresses():
                if ':' not in address and address != '127.0.0.1':
                    print(f"Phone browser camera: https://{address}:{args.https_port}/setup#phone-camera",flush=True)
            print("Local HTTPS certificate: your browser may ask you to trust this laptop before allowing the camera.",flush=True)
            threading.Thread(target=http.run,daemon=True,name='http-server').start()
            tls.start()
        else:
            http.run()
    finally:
        app.extensions["close"]()
        if tls:
            tls.stop()
        if http:
            http.close()
            http.task_dispatcher.shutdown(timeout=2)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
