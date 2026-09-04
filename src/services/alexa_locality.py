from __future__ import annotations

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.clients.alexa_settings import AlexaSettingsClient


class AlexaLocalitySupport:
    FULL_ADDRESS_SCOPES = (
        permission_scopes.DEVICE_ADDRESS,
        permission_scopes.DEVICE_ADDRESS_FULL,
    )
    @staticmethod
    def has_any_profile_name(store: dict) -> bool:
        return bool(store.get("userName") or store.get("fullName"))

    @classmethod
    def has_full_address_permission(cls, handler_input) -> bool:
        return any(
            RequestContext.has_permission(handler_input, scope)
            for scope in cls.FULL_ADDRESS_SCOPES
        )

class AlexaLocalityService:
    __slots__ = ("_settings",)

    def __init__(self, settings: AlexaSettingsClient) -> None:
        self._settings = settings

    async def detect_device_location(self, handler_input) -> dict:
        geolocation = RequestContext.get_geolocation(handler_input)
        if geolocation:
            return {
                "_status": "resolved",
                "city": "",
                "locality": "",
                "countryCode": None,
                "postalCode": None,
                "stateOrRegion": None,
                "latitude": geolocation.get("latitude"),
                "longitude": geolocation.get("longitude"),
                "source": "geolocation",
            }
        if not AlexaLocalitySupport.has_full_address_permission(handler_input):
            if RequestContext.has_permission(handler_input, permission_scopes.GEOLOCATION_READ):
                return {"_status": "empty"}
            return {"_status": "permission_denied"}

        fetched = await self._settings.get_device_address(handler_input)
        address_status = fetched.get("_status")
        address = fetched if address_status == "granted" else None
        city = (
            (address or {}).get("city")
            or (address or {}).get("addressLine3")
            or (address or {}).get("districtOrCounty")
        )
        if not city:
            return {"_status": address_status or "unavailable"}
        return {
            "_status": "resolved",
            "city": str(city or "").strip(),
            "locality": str(city or "").strip(),
            "countryCode": (address or {}).get("countryCode"),
            "postalCode": (address or {}).get("postalCode"),
            "stateOrRegion": (address or {}).get("stateOrRegion"),
            "latitude": None,
            "longitude": None,
            "source": "device",
        }

    def get_missing_permissions(self, handler_input, store: dict) -> list[str]:
        missing: list[str] = []
        has_location_permission = (
            AlexaLocalitySupport.has_full_address_permission(handler_input)
            or RequestContext.has_permission(handler_input, permission_scopes.GEOLOCATION_READ)
        )
        if not has_location_permission and not store.get("latitude"):
            missing.append(permission_scopes.GEOLOCATION_READ)
        if not AlexaLocalitySupport.has_any_profile_name(store):
            missing.extend(self.get_profile_permissions_to_request(handler_input, store))
        return missing

    def get_profile_permissions_to_request(self, handler_input, store: dict) -> list[str]:
        if AlexaLocalitySupport.has_any_profile_name(store) or store.get("profileNameUnavailable"):
            return []
        requested: list[str] = []
        full_name_granted = RequestContext.has_permission(
            handler_input, permission_scopes.PROFILE_NAME_READ
        )
        if not full_name_granted or store.get("profileFetchDenied"):
            requested.append(permission_scopes.PROFILE_NAME_READ)
        return requested
