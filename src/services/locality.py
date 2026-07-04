from __future__ import annotations
import time
import httpx
from config import settings, permission_scopes
from src.services.persistence import get_store, update_store


def get_geolocation(handler_input) -> dict | None:
    """Extract latitude/longitude/accuracy from the Alexa request context."""
    try:
        geo = handler_input.request_envelope.context.Geolocation
    except Exception:
        return None
    if not geo or not geo.coordinate:
        return None
    return {
        "latitude": geo.coordinate.latitudeInDegrees,
        "longitude": geo.coordinate.longitudeInDegrees,
        "accuracy": geo.coordinate.accuracyInMeters,
        "timestamp": geo.timestamp,
    }


async def get_device_address(handler_input) -> dict | None:
    """Fetch the device's country-and-postal-code address via the Alexa API."""
    try:
        sys = handler_input.request_envelope.context.System
        if not sys.api_endpoint or sys.api_access_token is None or not (sys.device and sys.device.deviceId):
            return None
    except Exception:
        return None
    api_endpoint = sys.api_endpoint
    api_access_token = sys.api_access_token
    device_id = sys.device.deviceId
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{api_endpoint}/v1/devices/{device_id}/settings/address/countryAndPostalCode",
                headers={"Authorization": f"Bearer {api_access_token}"},
            )
            if resp.status_code == 403:
                return {"denied": True}
            if resp.status_code == 204:
                return None
            resp.raise_for_status()
            data = resp.json()
            return {"postalCode": data.get("postalCode"), "countryCode": data.get("countryCode")}
    except Exception:
        return None


def has_permission(handler_input, scope: str) -> bool:
    """Check whether the Alexa request grants the specified permission scope."""
    try:
        scopes = handler_input.request_envelope.context.System.user.permissions.scopes
        return (scopes or {}).get(scope, {}).get("status") == "GRANTED"
    except Exception:
        return False


def _parse_profile_setting_value(data) -> str | None:
    if data is None:
        return None
    if isinstance(data, str):
        return data.strip() or None
    if isinstance(data, dict):
        candidate = (
            data.get("name")
            or data.get("value")
            or data.get("givenName")
            or data.get("fullName")
            or data.get("email")
            or data.get("firstName")
            or data.get("profileName")
        )
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


async def _fetch_profile_setting_with_status(
    handler_input,
    setting_path: str,
    *,
    label: str = "",
    permission_scope: str | None = None,
) -> dict:
    try:
        sys = handler_input.request_envelope.context.System
        if not sys.api_endpoint or sys.api_access_token is None:
            return {"value": None, "status": 0}
    except Exception:
        return {"value": None, "status": 0}

    api_endpoint = sys.api_endpoint
    api_access_token = sys.api_access_token

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{api_endpoint}/v2/accounts/~current/settings/{setting_path}",
                headers={"Authorization": f"Bearer {api_access_token}", "Accept": "application/json"},
            )
            if resp.status_code in (403, 401):
                return {"value": None, "status": resp.status_code}
            if resp.status_code == 204:
                return {"value": None, "status": 204}
            data = resp.json()
            parsed = _parse_profile_setting_value(data)
            return {"value": parsed, "status": resp.status_code}
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 0)
        return {"value": None, "status": status}


async def _fetch_profile_setting(handler_input, setting_path: str, **kwargs) -> str | None:
    result = await _fetch_profile_setting_with_status(handler_input, setting_path, **kwargs)
    return result.get("value")


async def get_user_profile_name(handler_input) -> str | None:
    """Return the user's full profile name from Alexa."""
    return await _fetch_profile_setting(
        handler_input, "Profile.name", label="Profile.name",
        permission_scope=permission_scopes.PROFILE_NAME_READ,
    )


async def get_user_profile_given_name(handler_input) -> str | None:
    """Return the user's given name from Alexa."""
    return await _fetch_profile_setting(
        handler_input, "Profile.givenName", label="Profile.givenName",
        permission_scope=permission_scopes.PROFILE_GIVEN_NAME_READ,
    )


async def get_user_profile_family_name(handler_input) -> str | None:
    """Return the user's family name from Alexa."""
    return await _fetch_profile_setting(
        handler_input, "Profile.familyName", label="Profile.familyName",
        permission_scope=permission_scopes.PROFILE_FAMILY_NAME_READ,
    )


async def get_user_profile_email(handler_input) -> str | None:
    """Return the user's email address from Alexa."""
    return await _fetch_profile_setting(
        handler_input, "Profile.email", label="Profile.email",
        permission_scope=permission_scopes.PROFILE_EMAIL_READ,
    )


_PROFILE_TTL_MS = 24 * 60 * 60 * 1000
_PROFILE_BACKOFF_MS = 5 * 60 * 1000


async def ensure_listener_profile(handler_input, store: dict) -> dict:
    """Fetch and cache the user's Alexa profile if not already resolved.

    Returns a dict of store key-value pairs to merge into the session store.
    """
    active = store or {}
    patch: dict = {}
    now = int(time.time() * 1000)
    resolved_at = active.get("listenerProfileResolvedAt") or 0
    skip_until = active.get("listenerProfileSkipUntil") or 0
    has_any_name = bool(active.get("userName") or active.get("fullName") or active.get("givenName"))
    fully_resolved = has_any_name and active.get("userEmail")

    if fully_resolved and resolved_at and (now - resolved_at) < _PROFILE_TTL_MS:
        return patch
    if skip_until and now < skip_until:
        return patch

    need_name = not has_any_name
    need_email = not active.get("userEmail")
    if not need_name and not need_email:
        if not resolved_at or (now - resolved_at) >= _PROFILE_TTL_MS:
            patch["listenerProfileResolvedAt"] = now
        return patch

    fetch_statuses: list[int] = []

    if need_name:
        name_res = await _fetch_profile_setting_with_status(
            handler_input, "Profile.name", label="Profile.name",
            permission_scope=permission_scopes.PROFILE_NAME_READ,
        )
        given_res = await _fetch_profile_setting_with_status(
            handler_input, "Profile.givenName", label="Profile.givenName",
            permission_scope=permission_scopes.PROFILE_GIVEN_NAME_READ,
        )
        family_res = await _fetch_profile_setting_with_status(
            handler_input, "Profile.familyName", label="Profile.familyName",
            permission_scope=permission_scopes.PROFILE_FAMILY_NAME_READ,
        )
        fetch_statuses.extend([name_res["status"], given_res["status"], family_res["status"]])
        if name_res["value"]:
            patch["fullName"] = name_res["value"]
        if given_res["value"]:
            patch["givenName"] = given_res["value"]
        if family_res["value"]:
            patch["familyName"] = family_res["value"]

    if need_email:
        email_res = await _fetch_profile_setting_with_status(
            handler_input, "Profile.email", label="Profile.email",
            permission_scope=permission_scopes.PROFILE_EMAIL_READ,
        )
        fetch_statuses.append(email_res["status"])
        if email_res["value"]:
            patch["userEmail"] = email_res["value"]

    saw_403 = any(s in (403, 401) for s in fetch_statuses)
    saw_204 = any(s == 204 for s in fetch_statuses)
    saw_missing_token = any(s == 0 for s in fetch_statuses)
    granted_given_name = has_permission(handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ)

    should_retry = saw_403 or saw_missing_token or (not granted_given_name and (saw_403 or saw_204 or saw_missing_token))
    name_unavailable = granted_given_name and saw_204 and not saw_403

    if should_retry:
        patch["profileFetchDenied"] = True
        patch["profileNameUnavailable"] = False
    elif name_unavailable:
        patch["profileNameUnavailable"] = True
        patch["profileFetchDenied"] = False

    user_name = patch.get("fullName") or patch.get("givenName") or active.get("userName") or None
    if user_name:
        patch["userName"] = user_name
        patch["profileFetchDenied"] = False
        patch["profileNameUnavailable"] = False

    got_name = bool(user_name)
    got_email = bool(patch.get("userEmail"))
    if got_name and got_email:
        patch["listenerProfileResolvedAt"] = now
        patch["listenerProfileSkipUntil"] = None
    elif not got_name and not got_email and not name_unavailable:
        patch["listenerProfileSkipUntil"] = now + _PROFILE_BACKOFF_MS

    return patch


def has_any_profile_name(store: dict) -> bool:
    """Return True if the store contains any known profile name."""
    return bool(store.get("userName") or store.get("fullName") or store.get("givenName"))


async def apply_listener_profile(handler_input) -> dict:
    """Enrich the session store with profile data and return the updated store."""
    store = get_store(handler_input)
    patch = await ensure_listener_profile(handler_input, store)
    if patch:
        update_store(handler_input, patch)
    return get_store(handler_input)


def attach_profile_permission_if_needed(builder, handler_input, store: dict):
    """Attach a permissions-consent card to the response builder when needed."""
    permissions = get_missing_permissions(handler_input, store)
    if not permissions:
        return builder
    return builder.with_ask_for_permissions_consent_card(permissions)


def get_profile_permissions_to_request(handler_input, store: dict) -> list:
    if has_any_profile_name(store):
        return []
    if store.get("profileNameUnavailable"):
        return []
    requested: list[str] = []
    context_granted_given = has_permission(handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ)
    context_granted_full = has_permission(handler_input, permission_scopes.PROFILE_NAME_READ)
    if not context_granted_given or store.get("profileFetchDenied"):
        requested.append(permission_scopes.PROFILE_GIVEN_NAME_READ)
    if not context_granted_full and permission_scopes.PROFILE_GIVEN_NAME_READ not in requested:
        requested.append(permission_scopes.PROFILE_NAME_READ)
    return requested


def get_missing_permissions(handler_input, store: dict) -> list:
    """Return the list of Alexa permission scopes the user still needs to grant."""
    missing: list[str] = []
    if not has_permission(handler_input, permission_scopes.DEVICE_ADDRESS) and not store.get("devicePostalCode"):
        missing.append(permission_scopes.DEVICE_ADDRESS)
    if not has_any_profile_name(store):
        missing.extend(get_profile_permissions_to_request(handler_input, store))
    if not has_permission(handler_input, permission_scopes.GEOLOCATION_READ) and not store.get("latitude"):
        missing.append(permission_scopes.GEOLOCATION_READ)
    return missing


def build_address_permission_card() -> dict:
    """Build an Alexa permissions-consent card requesting device address access."""
    return {"type": "AskForPermissionsConsent", "permissions": [permission_scopes.DEVICE_ADDRESS]}
