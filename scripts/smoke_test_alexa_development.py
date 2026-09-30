from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SmokeCase:
    utterance: str
    expected_intent: str
    expected_slot: str | None = None


class AlexaSimulationClient:
    TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    API_URL = "https://api.amazonalexa.com/v2/skills"

    def __init__(
        self,
        skill_id: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        stage: str = "development",
        locale: str = "en-GB",
    ) -> None:
        self.skill_id = skill_id
        self.stage = stage
        self.locale = locale
        self.access_token = self._access_token(client_id, client_secret, refresh_token)

    def simulate(self, utterance: str, max_wait_seconds: int = 120) -> dict[str, Any]:
        payload = {
            "session": {"mode": "FORCE_NEW_SESSION"},
            "input": {"content": utterance},
            "device": {"locale": self.locale},
        }
        url = f"{self.API_URL}/{self.skill_id}/stages/{self.stage}/simulations"
        created = self._request_json("POST", url, payload)
        simulation_id = str(created.get("id") or "").strip()
        if not simulation_id:
            raise RuntimeError(f"Alexa simulation did not return an id: {created}")

        status_url = f"{url}/{simulation_id}"
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() <= deadline:
            result = self._request_json("GET", status_url)
            status = result.get("status")
            if status == "SUCCESSFUL":
                return result
            if status == "FAILED":
                message = (result.get("result") or {}).get("error", {}).get("message")
                raise RuntimeError(f"Alexa simulation failed: {message or result}")
            time.sleep(2)
        raise TimeoutError(f"Timed out waiting for Alexa simulation {simulation_id}")

    def _access_token(
        self, client_id: str, client_secret: str, refresh_token: str
    ) -> str:
        payload = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode()
        request = Request(
            self.TOKEN_URL,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        response = self._open_json(request)
        access_token = str(response.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Alexa token response did not contain an access token")
        return access_token

    def _request_json(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload else None
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        return self._open_json(request)

    @staticmethod
    def _open_json(request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode()
        except HTTPError as error:
            detail = error.read().decode()
            raise RuntimeError(f"Alexa API {error.code}: {detail}") from error
        return json.loads(raw) if raw else {}


def _invocations(simulation: dict[str, Any]) -> list[dict[str, Any]]:
    skill_info = (simulation.get("result") or {}).get("skillExecutionInfo") or {}
    invocations = skill_info.get("invocations") or []
    if isinstance(invocations, dict):
        invocations = [invocations]
    return [item for item in invocations if isinstance(item, dict)]


def _request_response(
    simulation: dict[str, Any], request_type: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for invocation in reversed(_invocations(simulation)):
        request_body = (invocation.get("invocationRequest") or {}).get("body") or {}
        request = request_body.get("request") or {}
        if request.get("type") == request_type:
            response_body = (invocation.get("invocationResponse") or {}).get("body") or {}
            return request, response_body
    raise RuntimeError(
        f"Alexa simulation did not invoke the skill with a {request_type}"
    )


def _intent_request(simulation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return _request_response(simulation, "IntentRequest")


def _spoken_response(response: dict[str, Any]) -> str:
    output = (response.get("response") or {}).get("outputSpeech") or {}
    return str(output.get("ssml") or output.get("text") or "")


def _launch_user_id(simulation: dict[str, Any]) -> str:
    for invocation in reversed(_invocations(simulation)):
        body = (invocation.get("invocationRequest") or {}).get("body") or {}
        request = body.get("request") or {}
        if request.get("type") != "LaunchRequest":
            continue
        system = (body.get("context") or {}).get("System") or {}
        user = system.get("user") or {}
        session_user = (body.get("session") or {}).get("user") or {}
        user_id = str(user.get("userId") or session_user.get("userId") or "").strip()
        if user_id:
            return user_id
    raise RuntimeError("Alexa launch simulation did not expose a skill user id")


def _aws_json(*args: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout or "{}")


def _resolve_listener_id(user_id: str) -> str:
    base_url = str(os.environ.get("HEAR_API_URL") or "").strip().rstrip("/")
    api_key = str(os.environ.get("HEAR_API_KEY") or "").strip()
    if not base_url or not api_key:
        raise RuntimeError("Hear API URL/key are required for launch verification")

    payload = json.dumps({"alexaUserId": user_id}, separators=(",", ":"))
    try:
        completed = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "10",
                "--user-agent",
                "HearAlexaLaunchVerifier/1.0",
                "--request",
                "POST",
                f"{base_url}/listeners/resolve",
                "--header",
                "Accept: application/json",
                "--header",
                "Content-Type: application/json",
                "--header",
                f"X-Api-Key: {api_key}",
                "--data-binary",
                "@-",
            ],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        raise RuntimeError(f"Hear API request failed: {detail}") from error

    result = json.loads(completed.stdout) if completed.stdout else {}
    listener_id = str((result or {}).get("listenerId") or "").strip()
    if not listener_id:
        raise RuntimeError(
            "Hear API did not resolve the Alexa simulator to a canonical listener"
        )
    return listener_id


def _clear_persistence_key(table_name: str, region: str, persistence_key: str) -> int:
    names = json.dumps({"#id": "id", "#scope": "scope"}, separators=(",", ":"))
    values = json.dumps({":id": {"S": persistence_key}}, separators=(",", ":"))
    keys: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None

    while True:
        query_args = [
            "dynamodb",
            "query",
            "--table-name",
            table_name,
            "--region",
            region,
            "--key-condition-expression",
            "#id = :id",
            "--expression-attribute-names",
            names,
            "--expression-attribute-values",
            values,
            "--projection-expression",
            "#id,#scope",
            "--output",
            "json",
        ]
        if last_key:
            query_args.extend(
                [
                    "--exclusive-start-key",
                    json.dumps(last_key, separators=(",", ":")),
                ]
            )
        page = _aws_json(*query_args)
        for item in page.get("Items") or []:
            if item.get("id") and item.get("scope"):
                keys.append({"id": item["id"], "scope": item["scope"]})
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break

    for key in keys:
        _aws_json(
            "dynamodb",
            "delete-item",
            "--table-name",
            table_name,
            "--region",
            region,
            "--key",
            json.dumps(key, separators=(",", ":")),
            "--output",
            "json",
        )
    return len(keys)


def _clear_listener_state(
    table_name: str,
    region: str,
    user_id: str,
    listener_id: str,
) -> int:
    stage = str(os.environ.get("STAGE") or "development").strip().lower()
    persistence_keys = {
        user_id,
        f"listener:{stage}:{listener_id}",
    }
    return sum(
        _clear_persistence_key(table_name, region, persistence_key)
        for persistence_key in persistence_keys
        if persistence_key
    )


def _assert_launch(
    client: AlexaSimulationClient,
    invocation_name: str,
    *,
    table_name: str,
    region: str,
) -> None:
    probe = client.simulate(f"open {invocation_name}")
    user_id = _launch_user_id(probe)
    listener_id = _resolve_listener_id(user_id)
    removed = _clear_listener_state(table_name, region, user_id, listener_id)
    print(
        "Reset Alexa simulation listener state "
        f"across alias and canonical keys ({removed} item(s))"
    )

    try:
        simulation = client.simulate(f"open {invocation_name}")
        _, response = _request_response(simulation, "LaunchRequest")
        if not isinstance(response, dict) or not response.get("version"):
            raise AssertionError("Launch returned no valid Alexa response envelope")

        speech = _spoken_response(response)
        normalized = speech.casefold()
        required = (
            "welcome to hear service",
            "free service",
            "volunteers across the uk",
            "hear dot media slash alexa",
            "may i check the address saved in your alexa account",
            "please say yes or no",
        )
        missing = [phrase for phrase in required if phrase not in normalized]
        if missing:
            raise AssertionError(
                f"First launch did not use the consent-first onboarding; "
                f"missing={missing!r} speech={speech!r}"
            )
        if "say my city is followed by your city" in normalized:
            raise AssertionError(
                f"Launch regressed to automatic town capture: {speech!r}"
            )

        print("PASS first launch -> consent-first Hear Service onboarding")
    finally:
        _clear_listener_state(table_name, region, user_id, listener_id)


def _assert_case(
    client: AlexaSimulationClient,
    invocation_name: str,
    case: SmokeCase,
) -> None:
    spoken = f"ask {invocation_name} to {case.utterance}"
    simulation = client.simulate(spoken)
    request, response = _intent_request(simulation)
    intent = request.get("intent") or {}
    actual_intent = intent.get("name")
    if actual_intent != case.expected_intent:
        raise AssertionError(
            f"{case.utterance!r}: expected {case.expected_intent}, got {actual_intent}"
        )

    if case.expected_slot:
        slot = (intent.get("slots") or {}).get(case.expected_slot) or {}
        if not str(slot.get("value") or "").strip():
            raise AssertionError(
                f"{case.utterance!r}: expected populated slot {case.expected_slot}"
            )

    if not isinstance(response, dict) or not response.get("version"):
        raise AssertionError(
            f"{case.utterance!r}: Lambda returned no valid Alexa response envelope"
        )

    print(
        f"PASS {case.utterance!r} -> {actual_intent}"
        + (f".{case.expected_slot}" if case.expected_slot else "")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--refresh-token", required=True)
    parser.add_argument("--invocation-name", default="test development")
    parser.add_argument("--table-name", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()

    client = AlexaSimulationClient(
        args.skill_id,
        args.client_id,
        args.client_secret,
        args.refresh_token,
    )
    _assert_launch(
        client,
        args.invocation_name,
        table_name=args.table_name,
        region=args.region,
    )
    time.sleep(1)

    cases = (
        SmokeCase(
            "set my location to southampton",
            "SearchLocationIntent",
            "location",
        ),
        SmokeCase("change my location", "SetLocationIntent"),
        SmokeCase("increase speed", "IncreaseSpeedIntent"),
        SmokeCase("set speed to first", "SetPlaybackSpeedIntent", "speed"),
        SmokeCase("find this month salmon", "SearchContentIntent", "searchQuery"),
        SmokeCase("I enjoyed it", "FeedbackResponseIntent", "feedback"),
        SmokeCase("number 1", "ClarifySelectionIntent", "selection"),
    )
    for case in cases:
        _assert_case(client, args.invocation_name, case)
        time.sleep(1)


if __name__ == "__main__":
    main()
