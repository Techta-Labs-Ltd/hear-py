from config import settings
from config.permission_scopes import DEVICE_ADDRESS, REMINDERS_READWRITE


def test_settings_loads_defaults():
    assert settings.HEAR_DDB_REGION == "eu-west-1"
    assert settings.feedback_trigger_ms == 90000
    assert settings.default_speed == 1.0
    assert settings.speeds == [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    assert settings.search_page_limit == 3


def test_permission_scopes():
    assert DEVICE_ADDRESS.startswith("alexa::")
    assert REMINDERS_READWRITE.startswith("alexa::")


def test_settings_api_timeout_default():
    assert settings.api_timeout_ms is None or settings.api_timeout_ms > 0
    assert settings.api_retry_count >= 0
