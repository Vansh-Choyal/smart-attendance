"""Encrypt camera configuration at rest. Windows uses current-user DPAPI."""
import ctypes
import json
import os
from pathlib import Path


def atomic_write(path, content):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _dpapi(data, encrypt):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    crypt = ctypes.windll.crypt32
    if encrypt:
        ok = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise OSError("Windows could not unlock the saved camera configuration for this account.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


class SecureStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "camera.enc"

    def _fernet(self):
        from cryptography.fernet import Fernet
        key_path = self.directory / "camera.key"
        if not key_path.exists():
            atomic_write(key_path, Fernet.generate_key())
        return Fernet(key_path.read_bytes())

    def save(self, value):
        raw = json.dumps(value).encode()
        encrypted = b"DP1" + _dpapi(raw, True) if os.name == "nt" else b"FN1" + self._fernet().encrypt(raw)
        atomic_write(self.path, encrypted)

    def load(self):
        if not self.path.exists():
            return None
        raw = self.path.read_bytes()
        if raw[:3] == b"DP1" and os.name == "nt":
            return json.loads(_dpapi(raw[3:], False))
        if raw[:3] == b"FN1":
            return json.loads(self._fernet().decrypt(raw[3:]))
        raise ValueError("Saved camera configuration cannot be decrypted on this computer.")
