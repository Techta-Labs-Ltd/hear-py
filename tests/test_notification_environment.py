"""Keep both Alexa stages on the explicitly selected shared backend."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_notification_environment.py"
API = "https://alexa.hear.media/api/v1"
WEBHOOK = "https://alexa.hear.media/api/v1/webhooks/event"


def run_check(environment: str, overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HEAR_API_URL": API, "WEBHOOK_OUTBOUND_URL": WEBHOOK, **(overrides or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--environment", environment],
        env=env, capture_output=True, text=True, timeout=5, check=False,
    )


@pytest.mark.parametrize("environment", ["development", "production"])
def test_both_stages_accept_shared_hear_media_endpoint(environment):
    result = run_check(environment)
    assert result.returncode == 0, result.stderr
    assert "shared backend alexa.hear.media" in result.stdout


@pytest.mark.parametrize("environment", ["development", "production"])
@pytest.mark.parametrize("key", ["HEAR_API_URL", "WEBHOOK_OUTBOUND_URL"])
@pytest.mark.parametrize("invalid", [
    "https://alexa.hear.surf/api/v1",
    "http://alexa.hear.media/api/v1",
    "https://alexa.hear.media.example.invalid/api/v1",
    "",
])
def test_wrong_host_or_insecure_endpoint_is_still_rejected(environment, key, invalid):
    result = run_check(environment, {key: invalid})
    assert result.returncode != 0
    assert key in result.stderr
    assert "shared Alexa hostname alexa.hear.media" in result.stderr


@pytest.mark.parametrize("filename,stage", [("deploy-develop.yml", "DEV"), ("deploy-main.yml", "PROD")])
def test_workflow_defaults_use_shared_backend(filename, stage):
    workflow = (ROOT / ".github/workflows" / filename).read_text()
    assert f"HEAR_API_URL: ${{{{ vars.HEAR_API_URL_{stage} || '{API}' }}}}" in workflow
    assert f"WEBHOOK_OUTBOUND_URL: ${{{{ vars.WEBHOOK_OUTBOUND_URL_{stage} || '{WEBHOOK}' }}}}" in workflow
    assert "https://alexa.hear.surf" not in workflow
    assert "scripts/check_notification_environment.py" in workflow
