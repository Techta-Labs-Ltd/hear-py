from config.permission_scopes import (
    DEVICE_ADDRESS,
    GEOLOCATION_READ,
)
from src.constants.discovery import DiscoveryConstants


class OnboardingConstants:
    ASK_PERMISSION = "ask_permission"
    ASK_TOWN = "ask_town"
    AWAIT_LOCATION_CONFIRMATION = "await_location_confirm"
    ONBOARDING_ASK_TOWN = ASK_TOWN
    ONBOARDING_AWAIT_CONFIRM = AWAIT_LOCATION_CONFIRMATION
    MAX_TOWN_ATTEMPTS = 3
    MAX_TOWN_RESOLVER_FAILURES = 2
    PERMISSIONS = {
        "DEVICE_ADDRESS": DEVICE_ADDRESS,
        "GEOLOCATION": GEOLOCATION_READ,
    }
    LOCATION_VOICE_PERMISSIONS = (GEOLOCATION_READ,)
    TOWN_CONFIRM_REPROMPT = "Say yes to confirm, or no to set a different city."
    TOWN_SKIP_PHRASES = DiscoveryConstants.FEEDBACK_SKIP_HINTS
    CONTENT_REQUEST_PHRASES = (
        DiscoveryConstants.BROWSE_HINTS
        | DiscoveryConstants.LOCAL_HINTS
        | DiscoveryConstants.TRENDING_HINTS
    )
