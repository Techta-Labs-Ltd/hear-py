from pathlib import Path
from types import SimpleNamespace

from config import Settings, settings
from config.permission_scopes import DEVICE_ADDRESS, REMINDERS_READWRITE
from src.utils.deadline import DeadlineBudget


def test_settings_loads_defaults():
    assert settings.HEAR_DDB_REGION == "eu-west-1"
    assert settings.feedback_trigger_ms == 90000
    assert settings.default_speed == 1.0
    assert settings.speeds == [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    assert settings.search_page_limit == 3


def test_permission_scopes():
    assert DEVICE_ADDRESS == "read::alexa:device:all:address"
    assert REMINDERS_READWRITE.startswith("alexa::")


def test_settings_api_timeout_default():
    assert settings.api_timeout_ms is None or settings.api_timeout_ms > 0
    assert settings.api_retry_count >= 0


def test_runtime_flags_are_loaded_through_settings():
    configured = Settings(
        _env_file=None,
        HEAR_PROGRESSIVE_RESPONSES=False,
        HEAR_RESOLVER_URL="https://resolver.test",
        HEAR_RESOLVER_TIMEOUT_MS=2400,
        HEAR_PLAYBACK_SPEEDS="0.75,1.0,1.5",
        HEAR_DEFAULT_PLAYBACK_SPEED=1.5,
        HEAR_SEEK_STEP_MS=15000,
        HEAR_MAX_HISTORY=12,
    )
    assert configured.progressive_responses_enabled is False
    assert configured.HEAR_RESOLVER_URL == "https://resolver.test"
    assert configured.HEAR_RESOLVER_TIMEOUT_MS == 2400
    assert configured.speeds == [0.75, 1.0, 1.5]
    assert configured.default_speed == 1.5
    assert configured.seek_step_ms == 15000
    assert configured.max_history == 12


def test_env_example_documents_every_application_setting():
    path = Path(__file__).resolve().parents[1] / ".env.example"
    documented = {
        line.split("=", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    required = {
        name
        for name in Settings.model_fields
        if name.startswith(("HEAR_", "SENTRY_", "POWERTOOLS_", "SQS_", "WEBHOOK_"))
        or name in {"STAGE", "NODE_ENV", "DEBUG_HEAR", "AWS_REGION"}
    }
    assert required == documented


def test_outbound_timeout_never_exceeds_remaining_lambda_budget(monkeypatch):
    monkeypatch.setattr(DeadlineBudget, "_is_lambda", staticmethod(lambda: True))
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 900)
    handler_input = SimpleNamespace(context=context)
    assert DeadlineBudget.outbound_timeout_ms(handler_input, 10000, reserve_ms=800) == 100
    assert DeadlineBudget.compute_search_timeout_ms(handler_input) == 200
