import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from services.secure_store import atomic_write


def initialize_auth(directory, pin=None):
    secret_path = directory / "session.key"
    if not secret_path.exists():
        atomic_write(secret_path, secrets.token_bytes(32))
    credentials = directory / "admin.json"
    if pin is not None or not credentials.exists():
        generated = pin or str(secrets.randbelow(90_000_000) + 10_000_000)
        if len(generated) < 6:
            raise ValueError("Use an operator PIN or passphrase of at least 6 characters.")
        atomic_write(credentials, json.dumps({"hash": generate_password_hash(generated)}).encode())
        if pin is None:
            print(f"\nAttend operator PIN (keep private): {generated}\nUse --set-pin to change it.\n", flush=True)
    return secret_path.read_bytes(), json.loads(credentials.read_text())["hash"]


def operator_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not session.get("operator"):
            return jsonify(ok=False, error={"code": "authentication_required", "message": "Unlock the operator controls to continue."}), 401
        return handler(*args, **kwargs)
    return wrapped


class AuthGuard:
    def __init__(self, app):
        self.lock = threading.Lock()
        self.attempts = {}
        self.hostname = socket.gethostname().lower()
        app.before_request(self.before_request)

    def before_request(self):
        # In LAN mode, public clients remain rejected.
        try:
            remote = ipaddress.ip_address(request.remote_addr)
            host = request.host.split(":")[0].lower() if not request.host.startswith("[") else request.host[1:].split("]")[0]
            try:
                host_ip = ipaddress.ip_address(host)
                valid_host = (host_ip.is_private or host_ip.is_loopback) and not host_ip.is_unspecified
            except ValueError:
                valid_host = host in {"localhost", self.hostname, self.hostname + ".local"}
            allowed = remote.is_loopback or (current_app.config["LAN_MODE"] and remote.is_private)
            if not allowed or not valid_host:
                return jsonify(ok=False, error={"code": "local_only", "message": "Attend is available only on this computer or its authorized local network."}), 403
        except ValueError:
            return jsonify(ok=False, error={"code": "invalid_host", "message": "Invalid local address."}), 400
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf", "")
            origin = request.headers.get("Origin")
            if (not token or not expected or not hmac.compare_digest(token, expected)
                    or (origin and urlsplit(origin).netloc != request.host)):
                return jsonify(ok=False, error={"code": "csrf_failed", "message": "Your page session expired. Refresh and try again."}), 403

    def login(self, pin):
        address = request.remote_addr
        now = time.monotonic()
        with self.lock:
            # Limit both a client and the whole server; expire unused buckets.
            self.attempts = {key: [stamp for stamp in stamps if now-stamp < 60]
                             for key, stamps in self.attempts.items() if any(now-stamp < 60 for stamp in stamps)}
            local = self.attempts.setdefault(address, [])
            total = self.attempts.setdefault("*", [])
            if len(local) >= 8 or len(total) >= 30:
                return False, True
            local.append(now)
            total.append(now)
            valid = isinstance(pin, str) and len(pin) <= 128 and check_password_hash(current_app.config["PIN_HASH"], pin)
            if valid:
                self.attempts.pop(address, None)
                session.clear()
                session["operator"] = True
                session["csrf"] = secrets.token_urlsafe(32)
                session.permanent = True
            return valid, False
