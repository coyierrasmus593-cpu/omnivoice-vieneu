# -*- coding: utf-8 -*-
"""
License Client for OmniVoice Cloner.
Adapted from V3.4 license_client_secure.py for AI86.PRO Voice Cloner & TTS.
"""
import base64
import os
import sys

# ==============================================================================
# ANTI-DEBUG — runs on import
# ==============================================================================
def _anti_debug() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.IsDebuggerPresent():
            os._exit(1)
    except Exception:
        pass

_anti_debug()

# ==============================================================================
# OBFUSCATION LAYER 1: Split and encoded constants
# ==============================================================================
_pa = "dqYJZLKt"
_pb = "z2Zq0212"
_pc = "L/FUaC/j"
_pd = "MhwFcvyU"
_pe = "PRYXIhGhWh4="
_PUBLIC_KEY_B64 = _pa + _pb + _pc + _pd + _pe

# API URLs (base64 encoded)
_API_URL_ENC = "aHR0cHM6Ly9zeW5jLmdvbWh1b25nY2FuaC52bg=="
_API_URL = base64.b64decode(_API_URL_ENC).decode()

_API_URL_FALLBACK_ENC = "aHR0cHM6Ly92ZXJpZnkuYWk4Ni5jbGljaw=="
_API_URL_FALLBACK = base64.b64decode(_API_URL_FALLBACK_ENC).decode()

_API_URL_DAILY_ENC = "aHR0cHM6Ly9kYWlseWFpODYub25saW5l"
_API_URL_DAILY = base64.b64decode(_API_URL_DAILY_ENC).decode()

# App identity
_APP_ID = "ai-tts1"
_APP_VERSION = "omnivoice-1.0.0"

# Pepper for HKDF
_PEPPER = b"omnivoice-" + b"cloner-" + b"pepper-2025-v1"

# ==============================================================================
# IMPORTS
# ==============================================================================
try:
    import hashlib
    import json
    import platform
    import struct
    import time
    import uuid
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from urllib import error, request as urllib_request

    import nacl.encoding
    import nacl.exceptions
    import nacl.signing
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except ImportError as e:
    print(f"[license] Import error: {e}")
    print("[license] Install: pip install cryptography pynacl")
    # Don't sys.exit — allow app to run without license in dev mode
    nacl = None
    AESGCM = None

# ==============================================================================
# TIME HELPERS
# ==============================================================================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _parse_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
    return None

# ==============================================================================
# PATHS
# ==============================================================================
def _base_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    instance_suffix = "shared"
    try:
        if getattr(sys, "frozen", False):
            install_root = str(Path(sys.executable).resolve().parent)
            instance_suffix = hashlib.sha256(install_root.encode("utf-8")).hexdigest()[:10]
    except Exception:
        instance_suffix = "shared"
    return Path(base) / f"OmniVoiceCloner_{instance_suffix}"

def _license_path() -> Path:
    return _base_dir() / "license.bin"

def _device_fallback_path() -> Path:
    return _base_dir() / "device_fallback.id"

def _diag_log_path() -> Path:
    return _base_dir() / "license_diagnostics.log"

def _diag(message: str) -> None:
    try:
        p = _diag_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except Exception:
        pass

# ==============================================================================
# MACHINE ID — MachineGuid|VolumeSerial|CPUName
# ==============================================================================
def _read_windows_machine_guid():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        return None

def _read_volume_serial():
    try:
        import ctypes
        serial = ctypes.c_uint32(0)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p("C:\\"), None, 0, ctypes.byref(serial), None, None, None, 0,
        )
        return str(serial.value) if serial.value else None
    except Exception:
        return None

def _read_cpu_name():
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        return None

_MACHINE_ID_CACHE = None

def _get_machine_id() -> str:
    global _MACHINE_ID_CACHE
    if _MACHINE_ID_CACHE:
        return _MACHINE_ID_CACHE

    parts = [
        _read_windows_machine_guid() or "",
        _read_volume_serial() or "",
        _read_cpu_name() or "",
    ]
    raw = "|".join(parts)
    if not any(parts):
        raw = f"{uuid.getnode()}|{platform.node()}"

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    normalised = "".join(c for c in digest.upper() if c.isalnum())

    try:
        p = _device_fallback_path()
        if p.exists():
            cached = p.read_text(encoding="utf-8").strip()
            if cached == normalised:
                _MACHINE_ID_CACHE = normalised
                return normalised
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(normalised, encoding="utf-8")
    except Exception:
        pass

    _MACHINE_ID_CACHE = normalised
    return normalised

# ==============================================================================
# ED25519 VERIFICATION
# ==============================================================================
def _verify_ed25519_token(token_b64: str) -> dict:
    if nacl is None:
        raise RuntimeError("pynacl not installed")
    try:
        signed_bytes = base64.b64decode(token_b64)
    except Exception as exc:
        raise RuntimeError("invalid token encoding") from exc

    vk = nacl.signing.VerifyKey(_PUBLIC_KEY_B64, encoder=nacl.encoding.Base64Encoder)
    try:
        payload_bytes = vk.verify(signed_bytes)
    except nacl.exceptions.BadSignatureError as exc:
        raise RuntimeError("invalid token signature") from exc

    try:
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("invalid token payload") from exc

# ==============================================================================
# ENCRYPTED STORAGE (AESGCM + HKDF + DPAPI)
# ==============================================================================
def _derive_key(device_code: str, kid: str, exp_utc: str, salt: bytes) -> bytes:
    info = f"{device_code}|{kid}|{exp_utc}".encode("utf-8") + _PEPPER
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=salt, info=info)
    return hkdf.derive(b"license-encryption-key")

def _encrypt_token(token_data: bytes, device_code: str, kid: str, exp_utc: str) -> bytes:
    salt = os.urandom(16)
    key = _derive_key(device_code, kid, exp_utc, salt)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, token_data, None)
    kid_b = kid.encode("utf-8")
    exp_b = exp_utc.encode("utf-8")
    return (
        salt + nonce
        + struct.pack(">H", len(kid_b)) + kid_b
        + struct.pack(">H", len(exp_b)) + exp_b
        + ct
    )

def _decrypt_token(blob: bytes, device_code: str) -> bytes:
    try:
        offset = 0
        salt = blob[offset:offset + 16]; offset += 16
        nonce = blob[offset:offset + 12]; offset += 12
        kid_len = struct.unpack(">H", blob[offset:offset + 2])[0]; offset += 2
        kid = blob[offset:offset + kid_len].decode("utf-8"); offset += kid_len
        exp_len = struct.unpack(">H", blob[offset:offset + 2])[0]; offset += 2
        exp_utc = blob[offset:offset + exp_len].decode("utf-8"); offset += exp_len
        ct = blob[offset:]
        return AESGCM(_derive_key(device_code, kid, exp_utc, salt)).decrypt(nonce, ct, None)
    except Exception as exc:
        raise RuntimeError("decryption failed") from exc

def _dpapi_protect(data: bytes) -> bytes:
    try:
        import ctypes
        import ctypes.wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        inp = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            raise RuntimeError("DPAPI protect failed")
        protected = ctypes.string_at(out.pbData, out.cbData)
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return protected
    except RuntimeError:
        raise
    except Exception:
        return b"\x00" + data

def _dpapi_unprotect(blob: bytes) -> bytes:
    if blob and blob[0:1] == b"\x00":
        return blob[1:]
    try:
        import ctypes
        import ctypes.wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        inp = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            raise RuntimeError("DPAPI unprotect failed")
        unprotected = ctypes.string_at(out.pbData, out.cbData)
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return unprotected
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("DPAPI unavailable") from exc

def _save_token(token_b64: str, kid: str, exp_utc: str) -> None:
    device_code = _get_machine_id()
    encrypted = _encrypt_token(token_b64.encode("utf-8"), device_code, kid, exp_utc)
    protected = _dpapi_protect(encrypted)
    path = _license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protected)

def _load_token() -> str | None:
    path = _license_path()
    if not path.exists():
        _diag(f"token file not found: {path.name}")
        return None
    try:
        protected = path.read_bytes()
        encrypted = _dpapi_unprotect(protected)
        token_bytes = _decrypt_token(encrypted, _get_machine_id())
        return token_bytes.decode("utf-8")
    except Exception as exc:
        _diag(f"token load/decrypt error: {exc}")
        return None

def _verify_stored_token(token_b64: str) -> dict | None:
    try:
        payload = _verify_ed25519_token(token_b64)
    except RuntimeError as exc:
        _diag(f"stored token signature fail: {exc}")
        return None
    token_device = "".join(c for c in payload.get("device_code", "").upper() if c.isalnum())
    local_machine = _get_machine_id()
    if token_device != local_machine:
        _diag(f"stored token device mismatch")
        return None
    exp = _parse_time(payload.get("exp_utc"))
    if not exp or _utcnow() >= exp:
        _diag(f"stored token expired: exp={exp}")
        return None
    _diag("stored token ok")
    return payload

# ==============================================================================
# SERVER COMMUNICATION
# ==============================================================================
def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        msg = ""
        if exc.fp:
            try:
                body_txt = exc.read().decode("utf-8", errors="ignore")
                parsed = json.loads(body_txt)
                msg = str(parsed.get("error") or parsed.get("message") or "").strip()
            except Exception:
                pass
        raise RuntimeError(msg or f"HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(getattr(exc, "reason", exc))) from exc

    data = json.loads(raw)
    if isinstance(data, dict) and data.get("ok") is False:
        msg = str(data.get("error") or data.get("message") or "license rejected").strip()
        raise RuntimeError(msg)
    return data

def _candidate_endpoint_urls(base: str, endpoint: str) -> list[str]:
    b = base.rstrip("/")
    ep = endpoint.lstrip("/")
    return [f"{b}/api/{ep}", f"{b}/{ep}"]

def _post_with_failover(endpoint: str, payload: dict) -> dict:
    last_err = None
    servers = [_API_URL, _API_URL_DAILY, _API_URL_FALLBACK]
    for base in servers:
        for url in _candidate_endpoint_urls(base, endpoint):
            try:
                return _post_json(url, payload)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if any(t in msg for t in ("invalid", "rejected", "revoked", "expired", "device")):
                    raise
                last_err = exc
                _diag(f"failover: {url} failed: {exc}")
                continue
    raise last_err or RuntimeError("all servers unreachable")

# ==============================================================================
# MAIN LICENSE MANAGER CLASS
# ==============================================================================
class LicenseManager:
    _instance = None
    _lock = False

    VERIFY_INTERVAL = 86400
    OFFLINE_GRACE_DAYS = 7
    MAX_OFFLINE_GRACE_DAYS = 30
    MIN_CHECK_INTERVAL = 5

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized or self._lock:
            return
        self._lock = True
        try:
            self._cache_at: datetime | None = None
            self._cache_result: dict | None = None
            self._initialized = True
        finally:
            self._lock = False

    def save(self, key: str) -> bool:
        try:
            result = self.verify(key)
            return result.get("valid", False)
        except Exception as e:
            _diag(f"save error: {e}")
            return False

    def load(self) -> str | None:
        token_b64 = _load_token()
        if not token_b64:
            return None
        payload = _verify_stored_token(token_b64)
        if not payload:
            return None
        return payload.get("license_key") or "__token_ok__"

    def clear(self) -> bool:
        try:
            path = _license_path()
            if path.exists():
                path.unlink()
            self._cache_at = None
            self._cache_result = None
            return True
        except Exception:
            return False

    def get_machine_id(self) -> str:
        return _get_machine_id()

    def verify(self, license_key: str) -> dict:
        now = _utcnow()

        if (self._cache_at and self._cache_result and
                (now - self._cache_at).total_seconds() < self.MIN_CHECK_INTERVAL):
            return self._cache_result

        machine_id = _get_machine_id()
        _diag(f"verify start key={license_key[:4]}**** machine={machine_id[:8]}")

        # Try stored token first
        token_b64 = _load_token()
        if token_b64:
            payload = _verify_stored_token(token_b64)
            if payload:
                stored_key = payload.get("license_key", "")
                if stored_key == license_key or stored_key == "" or license_key == "__token_ok__":
                    result = self._check_token(token_b64, payload, now)
                    if result.get("valid"):
                        result["machine_id"] = machine_id
                        self._set_cache(now, result)
                        return result

        # No valid token → activate
        result = self._activate(license_key, now)
        result["machine_id"] = machine_id
        return result

    def _activate(self, license_key: str, now: datetime) -> dict:
        try:
            data = _post_with_failover("license/activate", {
                "licenseKey": license_key,
                "machineId": _get_machine_id(),
                "appId": _APP_ID,
                "appVersion": _APP_VERSION,
            })
        except RuntimeError as exc:
            err = str(exc)
            _diag(f"activate failed: {err}")
            result = {"valid": False, "message": err}
            self._set_cache(now, result)
            return result

        token_b64 = data.get("token") or data.get("accessToken") or data.get("access_token")
        if not token_b64:
            result = {"valid": False, "message": "invalid server response: missing token"}
            self._set_cache(now, result)
            return result

        try:
            token_payload = _verify_ed25519_token(token_b64)
            kid = token_payload.get("kid", "")
            exp_utc = token_payload.get("exp_utc", "")
        except RuntimeError:
            kid = data.get("kid", os.urandom(8).hex())
            exp_dt = _parse_time(data.get("expiresAt") or data.get("expires_at") or data.get("exp"))
            exp_utc = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if exp_dt else ""
            token_payload = {}

        if not exp_utc:
            result = {"valid": False, "message": "invalid server response: missing expiry"}
            self._set_cache(now, result)
            return result

        try:
            _save_token(token_b64, kid, exp_utc)
        except Exception as e:
            _diag(f"save token error: {e}")

        exp_dt = _parse_time(exp_utc)
        days_left = max(0, int((exp_dt - now).total_seconds() / 86400)) if exp_dt else 0

        tp = token_payload if isinstance(token_payload, dict) else {}
        result = {
            "valid": True,
            "message": "OK",
            "license_key": tp.get("license_key") or license_key,
            "days_left": data.get("daysLeft") or days_left,
            "username": tp.get("username") or data.get("username", ""),
            "email": tp.get("email") or data.get("email", ""),
            "app_id": tp.get("app_id") or data.get("appId", ""),
            "expiry": int(exp_dt.timestamp()) if exp_dt else None,
        }
        _diag(f"activate ok days={days_left}")
        self._set_cache(now, result)
        return result

    def _check_token(self, token_b64: str, payload: dict, now: datetime) -> dict:
        exp_dt = _parse_time(payload.get("exp_utc"))
        days_left = max(0, int((exp_dt - now).total_seconds() / 86400)) if exp_dt else 0

        base_result = {
            "valid": True,
            "message": "OK",
            "license_key": payload.get("license_key", ""),
            "days_left": days_left,
            "username": payload.get("username", ""),
            "email": payload.get("email", ""),
            "expiry": int(exp_dt.timestamp()) if exp_dt else None,
        }

        iat = _parse_time(payload.get("iat")) or _parse_time(payload.get("last_verified"))
        needs_server_check = (not iat or (now - iat).total_seconds() >= self.VERIFY_INTERVAL)

        if not needs_server_check:
            return base_result

        try:
            data = _post_with_failover("license/verify", {
                "token": token_b64,
                "machineId": _get_machine_id(),
                "appId": _APP_ID,
                "appVersion": _APP_VERSION,
            })
            if data.get("active") is False:
                return {"valid": False, "message": "license inactive"}
            _diag("token verify ok")
            return base_result
        except RuntimeError as exc:
            err = str(exc).lower()
            if any(t in err for t in ("revoked", "inactive", "device", "expired")):
                return {"valid": False, "message": str(exc)}
            grace = min(int(payload.get("offline_grace_days", self.OFFLINE_GRACE_DAYS)), self.MAX_OFFLINE_GRACE_DAYS)
            if iat and (now - iat) <= timedelta(days=grace):
                _diag(f"offline grace active: {exc}")
                return base_result
            return {"valid": False, "message": f"license_unverified: {exc}"}

    def _set_cache(self, at: datetime, result: dict) -> None:
        self._cache_at = at
        self._cache_result = result


# ==============================================================================
# PUBLIC API
# ==============================================================================
def get_license_manager() -> LicenseManager:
    return LicenseManager()

def get_machine_id() -> str:
    return _get_machine_id()
