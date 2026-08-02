"""Pure HMAC signing helpers shared by outbound event transports."""
from __future__ import annotations

import hashlib
import hmac
import time

from config import settings


def _constant_time_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for ca, cb in zip(a, b):
        diff |= ord(ca) ^ ord(cb)
    return diff == 0


def verify_signature(payload: str, signature_header: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 signature with timestamp tolerance."""
    if not payload or not signature_header or not secret:
        return False
    parts = {}
    for part in signature_header.split(","):
        key_value = part.split("=", 1)
        if len(key_value) == 2:
            parts[key_value[0].strip()] = key_value[1].strip()
    timestamp = parts.get("t")
    expected = parts.get("v1")
    if not timestamp or not expected:
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - timestamp_value) > settings.WEBHOOK_SIGNATURE_TOLERANCE_SECONDS:
        return False
    signed_payload = f"{timestamp}.{payload}"
    computed = hmac.new(
        secret.encode(), signed_payload.encode(), hashlib.sha256,
    ).hexdigest()
    return _constant_time_compare(computed, expected)


def sign_payload(payload: str, secret: str) -> dict:
    """Sign a payload with HMAC-SHA256."""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(), signed_payload.encode(), hashlib.sha256,
    ).hexdigest()
    return {
        "signature": f"t={timestamp},v1={signature}",
        "timestamp": timestamp,
    }


def signed_webhook_headers(payload: str, secret: str, api_key: str = "") -> dict:
    signature = sign_payload(payload, secret)
    headers = {
        "Content-Type": "application/json",
        "x-webhook-signature": signature["signature"],
        "x-webhook-timestamp": signature["timestamp"],
    }
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers
