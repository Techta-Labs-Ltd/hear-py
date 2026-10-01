from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SmokeCase:
    utterance: str
    expected_intent: str | tuple[str, ...]
    expected_slot: str | tuple[str, ...] | None = None
    response_contains: str | None = None


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



def _assert_launch(client: AlexaSimulationClient, invocation_name: str) -> None:
    simulation = client.simulate(f"open {invocation_name}")
    _, response = _request_response(simulation, "LaunchRequest")
    if not isinstance(response, dict) or not response.get("version"):
        raise AssertionError("Launch returned no valid Alexa response envelope")

    speech = _spoken_response(response)
    normalized = speech.casefold()
    if "welcome" in normalized and "hear service" not in normalized:
        raise AssertionError(
            f"Launch welcome did not use Hear Service branding: {speech!r}"
        )
    if "say my city is followed by your city" in normalized:
        raise AssertionError(
            f"Launch regressed to automatic town capture: {speech!r}"
        )

    print(f"PASS launch -> no automatic town capture; speech={speech}")

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
    expected_intents = (
        case.expected_intent
        if isinstance(case.expected_intent, tuple)
        else (case.expected_intent,)
    )
    if actual_intent not in expected_intents:
        raise AssertionError(
            f"{case.utterance!r}: expected one of {expected_intents}, got {actual_intent}"
        )

    if case.expected_slot:
        expected_slots = (
            case.expected_slot
            if isinstance(case.expected_slot, tuple)
            else (case.expected_slot,)
        )
        slots = intent.get("slots") or {}
        if not any(
            str((slots.get(slot_name) or {}).get("value") or "").strip()
            for slot_name in expected_slots
        ):
            raise AssertionError(
                f"{case.utterance!r}: expected populated slot in {expected_slots}"
            )

    if not isinstance(response, dict) or not response.get("version"):
        raise AssertionError(
            f"{case.utterance!r}: Lambda returned no valid Alexa response envelope"
        )

    if case.response_contains:
        speech = _spoken_response(response)
        if case.response_contains.casefold() not in speech.casefold():
            raise AssertionError(
                f"{case.utterance!r}: response did not contain "
                f"{case.response_contains!r}: {speech!r}"
            )

    populated = {
        name: str((slot or {}).get("value") or "").strip()
        for name, slot in (intent.get("slots") or {}).items()
        if str((slot or {}).get("value") or "").strip()
    }
    print(
        f"PASS {case.utterance!r} -> {actual_intent}"
        + (f".{case.expected_slot}" if case.expected_slot else "")
        + (f" slots={populated}" if populated else "")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--refresh-token", required=True)
    parser.add_argument("--invocation-name", default="test development")
    args = parser.parse_args()

    client = AlexaSimulationClient(
        args.skill_id,
        args.client_id,
        args.client_secret,
        args.refresh_token,
    )
    _assert_launch(client, args.invocation_name)
    time.sleep(1)

    cases = (
        SmokeCase(
            "my city is herne bay",
            ("TownCaptureIntent", "OpenDiscoveryIntent"),
            ("location", "searchQuery"),
        ),
        SmokeCase(
            "my city is chelmsford",
            "TownCaptureFallbackIntent",
            "locationQuery",
        ),
        SmokeCase(
            "my city is york",
            "TownCaptureFallbackIntent",
            "locationQuery",
        ),
        SmokeCase(
            "set my location to herne bay",
            ("SearchLocationIntent", "OpenDiscoveryIntent"),
            ("location", "searchQuery"),
        ),
        SmokeCase(
            "set my location to chelmsford",
            ("SearchLocationIntent", "SearchLocationFallbackIntent", "OpenDiscoveryIntent"),
            ("location", "locationQuery", "searchQuery"),
        ),
        SmokeCase("change my location", "SetLocationIntent"),
        SmokeCase("increase speed", "IncreaseSpeedIntent"),
        SmokeCase("forward", "FastForwardIntent"),
        SmokeCase("fast forward 30 seconds", "FastForwardIntent", ("time", "number")),
        SmokeCase("rewind 15 seconds", "RewindIntent", ("time", "number")),
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
