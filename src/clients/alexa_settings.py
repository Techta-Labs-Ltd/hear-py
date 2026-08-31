from __future__ import annotations

import json
import logging

from config import settings
from src.alexa.context import RequestContext
from src.clients.pool import HttpPool
from src.utils.deadline import DeadlineBudget


class AlexaSettingsSupport:
    logger = logging.getLogger(__name__)

    @staticmethod
    def _safe_address_log(data: dict) -> dict:
        return {
            "city": data.get("city"),
            "countryCode": data.get("countryCode"),
            "stateOrRegion": data.get("stateOrRegion"),
            "districtOrCounty": data.get("districtOrCounty"),
            "postalCodePresent": bool(data.get("postalCode")),
            "addressLine3Present": bool(data.get("addressLine3")),
        }

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


class AlexaSettingsClient:
    __slots__ = ("_pool",)

    def __init__(self, pool: HttpPool | None = None) -> None:
        self._pool = pool or HttpPool(timeout_ms=settings.HEAR_ALEXA_API_TIMEOUT_MS)

    async def get_device_address(self, handler_input) -> dict:
        system = RequestContext.get_system_context(handler_input)
        if not system or not system.apiEndpoint or system.apiAccessToken is None:
            return {"_status": "unavailable"}
        if not system.device or not system.device.deviceId:
            return {"_status": "unavailable"}
        api_endpoint = system.apiEndpoint
        api_access_token = system.apiAccessToken
        device_id = system.device.deviceId
        try:
            AlexaSettingsSupport.logger.info(
                "Hear: device address request method=GET apiEndpoint=%s path=/v1/devices/<redacted>/settings/address requestId=%s tokenPresent=%s deviceIdPresent=true",
                api_endpoint,
                RequestContext.get_request_id(handler_input),
                bool(api_access_token),
            )
            timeout = (
                DeadlineBudget.outbound_timeout_ms(
                    handler_input, settings.HEAR_ALEXA_API_TIMEOUT_MS
                )
                / 1000.0
            )
            response = await self._pool.get().get(
                f"{api_endpoint}/v1/devices/{device_id}/settings/address",
                headers={
                    "Authorization": f"Bearer {api_access_token}",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
            AlexaSettingsSupport.logger.info(
                "Hear: device address response status=%s requestId=%s",
                response.status_code,
                RequestContext.get_request_id(handler_input),
            )
            if response.status_code == 403:
                return {"_status": "permission_denied"}
            if response.status_code == 401:
                return {"_status": "unauthorized"}
            if response.status_code == 404:
                return {"_status": "not_found"}
            if response.status_code == 204:
                return {"_status": "empty"}
            response.raise_for_status()
            data = response.json()
            AlexaSettingsSupport.logger.info(
                "Hear: device address response data=%s requestId=%s",
                json.dumps(
                    AlexaSettingsSupport._safe_address_log(data),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                RequestContext.get_request_id(handler_input),
            )
            return {
                "_status": "granted",
                "city": data.get("city"),
                "postalCode": data.get("postalCode"),
                "countryCode": data.get("countryCode"),
                "stateOrRegion": data.get("stateOrRegion"),
                "districtOrCounty": data.get("districtOrCounty"),
                "addressLine3": data.get("addressLine3"),
            }
        except Exception as error:
            AlexaSettingsSupport.logger.warning(
                "Hear: device address API failed error=%s", type(error).__name__
            )
            return {"_status": "temporary_error"}

    async def get_profile_setting(
        self, handler_input, setting_path: str, *, label: str = ""
    ) -> dict:
        system = RequestContext.get_system_context(handler_input)
        if not system or not system.apiEndpoint or system.apiAccessToken is None:
            return {"value": None, "status": 0}
        try:
            AlexaSettingsSupport.logger.info(
                "Hear: profile setting request setting=%s requestId=%s tokenPresent=%s",
                label or setting_path,
                RequestContext.get_request_id(handler_input),
                bool(system.apiAccessToken),
            )
            timeout = (
                DeadlineBudget.outbound_timeout_ms(
                    handler_input, settings.HEAR_ALEXA_API_TIMEOUT_MS
                )
                / 1000.0
            )
            response = await self._pool.get().get(
                f"{system.apiEndpoint}/v2/accounts/~current/settings/{setting_path}",
                headers={
                    "Authorization": f"Bearer {system.apiAccessToken}",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
            if response.status_code in (401, 403):
                AlexaSettingsSupport.logger.info(
                    "Hear: profile setting response setting=%s status=%s valuePresent=false",
                    label or setting_path,
                    response.status_code,
                )
                return {"value": None, "status": response.status_code}
            if response.status_code == 204:
                AlexaSettingsSupport.logger.info(
                    "Hear: profile setting response setting=%s status=204 valuePresent=false",
                    label or setting_path,
                )
                return {"value": None, "status": 204}
            value = AlexaSettingsSupport._parse_profile_setting_value(response.json())
            AlexaSettingsSupport.logger.info(
                "Hear: profile setting response setting=%s status=%s valuePresent=%s",
                label or setting_path,
                response.status_code,
                bool(value),
            )
            return {"value": value, "status": response.status_code}
        except Exception as error:
            status = getattr(getattr(error, "response", None), "status_code", 0)
            return {"value": None, "status": status}
