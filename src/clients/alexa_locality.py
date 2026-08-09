from __future__ import annotations

import logging
import time

import config.permission_scopes as permission_scopes
from src.clients.pool import HttpPool
from src.services.store import get_store, update_store

_PROFILE_TTL_MS = 24 * 60 * 60 * 1000
_PROFILE_BACKOFF_MS = 5 * 60 * 1000
_GRANTED_STATUS = "GRANTED"
logger = logging.getLogger(__name__)

_LOCALITY_POOL = HttpPool(timeout_ms=10_000)


class AlexaLocalityClient:
    __slots__ = ("_pool",)

    def __init__(self, pool: HttpPool | None = None) -> None:
        self._pool = pool or _LOCALITY_POOL

    # -------------------------------------------------- permission helpers ----

    @staticmethod
    def has_permission(handler_input, scope: str) -> bool:
        try:
            scopes = handler_input.request_envelope.context.System.user.permissions.scopes
            return (scopes or {}).get(scope, {}).get("status") == _GRANTED_STATUS
        except Exception:
            return False

    # -------------------------------------------------- geolocation ----------

    @staticmethod
    def get_geolocation(handler_input) -> dict | None:
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

    # -------------------------------------------------- device address ------

    async def get_device_address(self, handler_input) -> dict | None:
        try:
            sys = handler_input.request_envelope.context.System
            if not sys.apiEndpoint or sys.apiAccessToken is None or not (sys.device and sys.device.deviceId):
                return {"_status": "unavailable"}
        except Exception:
            return {"_status": "unavailable"}
        api_endpoint = sys.apiEndpoint
        api_access_token = sys.apiAccessToken
        device_id = sys.device.deviceId
        try:
            client = self._pool.get()
            resp = await client.get(
                f"{api_endpoint}/v1/devices/{device_id}/settings/address",
                headers={
                    "Authorization": f"Bearer {api_access_token}",
                    "Accept": "application/json",
                },
            )
            logger.info("Hear: device address API status=%s", resp.status_code)
            if resp.status_code == 403:
                return {"_status": "permission_denied"}
            if resp.status_code == 401:
                return {"_status": "unauthorized"}
            if resp.status_code == 404:
                return {"_status": "not_found"}
            if resp.status_code == 204:
                return {"_status": "empty"}
            resp.raise_for_status()
            data = resp.json()
            return {
                "_status": "granted",
                "city": data.get("city"),
                "postalCode": data.get("postalCode"),
                "countryCode": data.get("countryCode"),
                "stateOrRegion": data.get("stateOrRegion"),
                "districtOrCounty": data.get("districtOrCounty"),
                "addressLine3": data.get("addressLine3"),
            }
        except Exception as exc:
            logger.warning(
                "Hear: device address API failed error=%s", type(exc).__name__,
            )
            return {"_status": "temporary_error"}

    # -------------------------------------------------- device location ------

    async def detect_device_location(self, handler_input) -> dict | None:
        # Amazon documents context.System.user.permissions as deprecated.
        # The Device Settings API response is the authoritative permission check.
        fetched = await self.get_device_address(handler_input)
        address_status = (fetched or {}).get("_status")
        address = fetched if address_status == "granted" else None
        geo = None
        if self.has_permission(handler_input, permission_scopes.GEOLOCATION_READ):
            geo = self.get_geolocation(handler_input)

        city = (
            (address or {}).get("city")
            or (address or {}).get("addressLine3")
            or (address or {}).get("districtOrCounty")
        )
        if not city and not geo:
            return {"_status": address_status or "unavailable"}
        return {
            "_status": "resolved",
            "city": str(city or "").strip(),
            "locality": str(city or "").strip(),
            "countryCode": (address or {}).get("countryCode"),
            "postalCode": (address or {}).get("postalCode"),
            "stateOrRegion": (address or {}).get("stateOrRegion"),
            "latitude": (geo or {}).get("latitude"),
            "longitude": (geo or {}).get("longitude"),
            "source": "device",
        }

    # -------------------------------------------------- profile helpers ------

    @staticmethod
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
        self,
        handler_input,
        setting_path: str,
        *,
        label: str = "",
        permission_scope: str | None = None,
    ) -> dict:
        try:
            sys = handler_input.request_envelope.context.System
            if not sys.apiEndpoint or sys.apiAccessToken is None:
                return {"value": None, "status": 0}
        except Exception:
            return {"value": None, "status": 0}
        api_endpoint = sys.apiEndpoint
        api_access_token = sys.apiAccessToken
        try:
            client = self._pool.get()
            resp = await client.get(
                f"{api_endpoint}/v2/accounts/~current/settings/{setting_path}",
                headers={
                    "Authorization": f"Bearer {api_access_token}",
                    "Accept": "application/json",
                },
            )
            if resp.status_code in (403, 401):
                return {"value": None, "status": resp.status_code}
            if resp.status_code == 204:
                return {"value": None, "status": 204}
            data = resp.json()
            parsed = self._parse_profile_setting_value(data)
            return {"value": parsed, "status": resp.status_code}
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", 0)
            return {"value": None, "status": status}

    # -------------------------------------------------- listener profile -----

    async def ensure_listener_profile(self, handler_input, store: dict) -> dict:
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
            name_res = await self._fetch_profile_setting_with_status(
                handler_input, "Profile.name", label="Profile.name",
                permission_scope=permission_scopes.PROFILE_NAME_READ,
            )
            given_res = await self._fetch_profile_setting_with_status(
                handler_input, "Profile.givenName", label="Profile.givenName",
                permission_scope=permission_scopes.PROFILE_GIVEN_NAME_READ,
            )
            family_res = await self._fetch_profile_setting_with_status(
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
            email_res = await self._fetch_profile_setting_with_status(
                handler_input, "Profile.email", label="Profile.email",
                permission_scope=permission_scopes.PROFILE_EMAIL_READ,
            )
            fetch_statuses.append(email_res["status"])
            if email_res["value"]:
                patch["userEmail"] = email_res["value"]

        saw_403 = any(s in (403, 401) for s in fetch_statuses)
        saw_204 = any(s == 204 for s in fetch_statuses)
        saw_missing_token = any(s == 0 for s in fetch_statuses)
        granted_given_name = self.has_permission(handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ)

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

    # -------------------------------------------------- public shortcuts -----

    @staticmethod
    def has_any_profile_name(store: dict) -> bool:
        return bool(store.get("userName") or store.get("fullName") or store.get("givenName"))

    async def apply_listener_profile(self, handler_input) -> dict:
        store = get_store(handler_input)
        patch = await self.ensure_listener_profile(handler_input, store)
        if patch:
            update_store(handler_input, patch)
        return get_store(handler_input)

    def attach_profile_permission_if_needed(self, builder, handler_input, store: dict):
        permissions = self.get_missing_permissions(handler_input, store)
        if not permissions:
            return builder
        return builder.with_ask_for_permissions_consent_card(permissions)

    def get_profile_permissions_to_request(self, handler_input, store: dict) -> list:
        if self.has_any_profile_name(store):
            return []
        if store.get("profileNameUnavailable"):
            return []
        requested: list[str] = []
        context_granted_given = self.has_permission(handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ)
        context_granted_full = self.has_permission(handler_input, permission_scopes.PROFILE_NAME_READ)
        if not context_granted_given or store.get("profileFetchDenied"):
            requested.append(permission_scopes.PROFILE_GIVEN_NAME_READ)
        if not context_granted_full and permission_scopes.PROFILE_GIVEN_NAME_READ not in requested:
            requested.append(permission_scopes.PROFILE_NAME_READ)
        return requested

    def get_missing_permissions(self, handler_input, store: dict) -> list:
        missing: list[str] = []
        if not self.has_permission(handler_input, permission_scopes.DEVICE_ADDRESS) and not store.get("devicePostalCode"):
            missing.append(permission_scopes.DEVICE_ADDRESS)
        if not self.has_any_profile_name(store):
            missing.extend(self.get_profile_permissions_to_request(handler_input, store))
        if not self.has_permission(handler_input, permission_scopes.GEOLOCATION_READ) and not store.get("latitude"):
            missing.append(permission_scopes.GEOLOCATION_READ)
        return missing
