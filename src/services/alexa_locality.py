from __future__ import annotations

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.clients.alexa_settings import AlexaSettingsClient


class AlexaLocalitySupport:
    @staticmethod
    def has_any_profile_name(store: dict) -> bool:
        return bool(store.get("userName") or store.get("fullName") or store.get("givenName"))


class AlexaLocalityService:
    __slots__ = ("_settings",)

    def __init__(self, settings: AlexaSettingsClient) -> None:
        self._settings = settings

    async def detect_device_location(self, handler_input) -> dict:
        if RequestContext.has_permission(handler_input, permission_scopes.DEVICE_ADDRESS):
            fetched = await self._settings.get_device_address(handler_input)
        elif RequestContext.has_permission(
            handler_input, permission_scopes.DEVICE_COUNTRY_POSTAL
        ):
            fetched = await self._settings.get_device_country_postal(handler_input)
        else:
            fetched = {"_status": "permission_denied"}
        address_status = fetched.get("_status")
        address = fetched if address_status == "granted" else None
        geolocation = (
            RequestContext.get_geolocation(handler_input)
            if RequestContext.has_permission(handler_input, permission_scopes.GEOLOCATION_READ)
            else None
        )
        city = (
            (address or {}).get("city")
            or (address or {}).get("addressLine3")
            or (address or {}).get("districtOrCounty")
        )
        if not city and not (address or {}).get("postalCode") and (not geolocation):
            return {"_status": address_status or "unavailable"}
        return {
            "_status": "resolved",
            "city": str(city or "").strip(),
            "locality": str(city or "").strip(),
            "countryCode": (address or {}).get("countryCode"),
            "postalCode": (address or {}).get("postalCode"),
            "stateOrRegion": (address or {}).get("stateOrRegion"),
            "latitude": (geolocation or {}).get("latitude"),
            "longitude": (geolocation or {}).get("longitude"),
            "source": "device",
        }

    def get_missing_permissions(self, handler_input, store: dict) -> list[str]:
        missing: list[str] = []
        if not RequestContext.has_permission(handler_input, permission_scopes.DEVICE_ADDRESS) and (
            not store.get("devicePostalCode")
        ):
            missing.append(permission_scopes.DEVICE_ADDRESS)
        if not AlexaLocalitySupport.has_any_profile_name(store):
            missing.extend(self.get_profile_permissions_to_request(handler_input, store))
        if not RequestContext.has_permission(
            handler_input, permission_scopes.GEOLOCATION_READ
        ) and (not store.get("latitude")):
            missing.append(permission_scopes.GEOLOCATION_READ)
        return missing

    def get_profile_permissions_to_request(self, handler_input, store: dict) -> list[str]:
        if AlexaLocalitySupport.has_any_profile_name(store) or store.get("profileNameUnavailable"):
            return []
        requested: list[str] = []
        given_name_granted = RequestContext.has_permission(
            handler_input, permission_scopes.PROFILE_GIVEN_NAME_READ
        )
        full_name_granted = RequestContext.has_permission(
            handler_input, permission_scopes.PROFILE_NAME_READ
        )
        if not given_name_granted or store.get("profileFetchDenied"):
            requested.append(permission_scopes.PROFILE_GIVEN_NAME_READ)
        if not full_name_granted and permission_scopes.PROFILE_GIVEN_NAME_READ not in requested:
            requested.append(permission_scopes.PROFILE_NAME_READ)
        return requested
