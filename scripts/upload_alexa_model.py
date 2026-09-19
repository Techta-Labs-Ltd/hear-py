from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AlexaModelUploader:
    TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    API_URL = "https://api.amazonalexa.com/v1/skills"

    def __init__(
        self,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._opener = opener
        self._sleeper = sleeper

    def upload(
        self,
        skill_id: str,
        locale: str,
        model_path: Path,
        invocation_name: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        max_wait_seconds: int,
    ) -> None:
        model = self._load_model(model_path, invocation_name)
        access_token = self._access_token(client_id, client_secret, refresh_token)
        model_url = self._model_url(skill_id, locale)
        self._request_json("PUT", model_url, model, access_token)
        self._wait_for_build(skill_id, locale, access_token, max_wait_seconds)
        self._verify_model(model_url, model, access_token)

    def _load_model(self, model_path: Path, invocation_name: str) -> dict[str, Any]:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        language_model = model.get("interactionModel", {}).get("languageModel")
        if not isinstance(language_model, dict):
            raise ValueError("Interaction model is missing languageModel")
        normalized_invocation = invocation_name.strip()
        if not normalized_invocation:
            raise ValueError("Alexa invocation name cannot be empty")
        language_model["invocationName"] = normalized_invocation
        return model

    def _access_token(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> str:
        response = self._request_json(
            "POST",
            self.TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            None,
            "application/x-www-form-urlencoded",
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Alexa token response did not contain an access token")
        return access_token

    def _wait_for_build(
        self,
        skill_id: str,
        locale: str,
        access_token: str,
        max_wait_seconds: int,
    ) -> None:
        status_url = f"{self.API_URL}/{skill_id}/status?resource=interactionModel"
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() <= deadline:
            response = self._request_json("GET", status_url, None, access_token)
            update = response.get("interactionModel", {}).get(locale, {}).get(
                "lastUpdateRequest", {}
            )
            status = update.get("status")
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise RuntimeError(f"Alexa interaction-model upload failed: {update}")
            self._sleeper(5)
        raise TimeoutError("Timed out waiting for the Alexa interaction-model upload")

    def _verify_model(
        self,
        model_url: str,
        expected_model: dict[str, Any],
        access_token: str,
    ) -> None:
        actual_model = self._request_json("GET", model_url, None, access_token)
        expected_language = expected_model["interactionModel"]["languageModel"]
        actual_language = actual_model["interactionModel"]["languageModel"]
        for field in ("invocationName", "intents", "types"):
            if actual_language.get(field) != expected_language.get(field):
                raise RuntimeError(f"Alexa interaction-model {field} did not match en-GB.json")

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        access_token: str | None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = (
                urlencode(payload).encode()
                if content_type == "application/x-www-form-urlencoded"
                else json.dumps(payload, separators=(",", ":")).encode()
            )
            headers["Content-Type"] = content_type
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener(request, timeout=30) as response:
                raw_response = response.read().decode()
        except HTTPError as error:
            detail = error.read().decode()
            raise RuntimeError(f"Alexa API {error.code}: {detail}") from error
        return json.loads(raw_response) if raw_response else {}

    def _model_url(self, skill_id: str, locale: str) -> str:
        return (
            f"{self.API_URL}/{skill_id}/stages/development/"
            f"interactionModel/locales/{locale}"
        )


class AlexaModelUploadCommand:
    @staticmethod
    def run() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--skill-id", required=True)
        parser.add_argument("--locale", default="en-GB")
        parser.add_argument("--model", type=Path, default=Path("en-GB.json"))
        parser.add_argument("--invocation-name", required=True)
        parser.add_argument("--client-id", required=True)
        parser.add_argument("--client-secret", required=True)
        parser.add_argument("--refresh-token", required=True)
        parser.add_argument("--max-wait-seconds", type=int, default=300)
        arguments = parser.parse_args()
        AlexaModelUploader().upload(
            arguments.skill_id,
            arguments.locale,
            arguments.model,
            arguments.invocation_name,
            arguments.client_id,
            arguments.client_secret,
            arguments.refresh_token,
            arguments.max_wait_seconds,
        )
        print(f"Alexa model uploaded for {arguments.locale}")


if __name__ == "__main__":
    AlexaModelUploadCommand.run()
