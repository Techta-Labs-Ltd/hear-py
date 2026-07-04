from __future__ import annotations

import hashlib
import hmac
import time

from config import settings


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks."""
    if len(a) != len(b):
        return False
    diff = 0
    for ca, cb in zip(a, b):
        diff |= ord(ca) ^ ord(cb)
    return diff == 0


def verify_signature(payload: str, signature_header: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 webhook signature with timestamp tolerance."""
    if not payload or not signature_header or not secret:
        return False

    parts: dict[str, str] = {}
    for part in signature_header.split(","):
        kv = part.split("=", 1)
        if len(kv) == 2:
            parts[kv[0].strip()] = kv[1].strip()

    timestamp = parts.get("t")
    expected_sig = parts.get("v1")
    if not timestamp or not expected_sig:
        return False

    now = int(time.time())
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    tolerance = settings.WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    if abs(now - ts) > tolerance:
        return False

    signed_payload = f"{timestamp}.{payload}"
    computed_sig = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return _constant_time_compare(computed_sig, expected_sig)


def sign_payload(payload: str, secret: str) -> dict:
    """Sign a payload with HMAC-SHA256 and return the signature header parts."""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {"signature": f"t={timestamp},v1={signature}", "timestamp": timestamp}
