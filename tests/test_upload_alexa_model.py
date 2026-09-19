from __future__ import annotations

import json
from pathlib import Path

from scripts.upload_alexa_model import AlexaModelUploader


class TestAlexaModelUploader:
    ROOT = Path(__file__).parents[1]

    def test_uploads_en_gb_without_changing_intents_or_slot_types(self):
        source = json.loads((self.ROOT / "en-GB.json").read_text(encoding="utf-8"))
        expected_model = json.loads(json.dumps(source))
        expected_model["interactionModel"]["languageModel"]["invocationName"] = "hear service"
        calls: list[tuple[str, str, dict | None]] = []
        statuses = iter(
            [
                {"interactionModel": {"en-GB": {"lastUpdateRequest": {"status": "IN_PROGRESS"}}}},
                {"interactionModel": {"en-GB": {"lastUpdateRequest": {"status": "SUCCEEDED"}}}},
            ]
        )

        class Uploader(AlexaModelUploader):
            def _request_json(self, method, url, payload, access_token, content_type="application/json"):
                calls.append((method, url, payload))
                if url == self.TOKEN_URL:
                    return {"access_token": "access"}
                if url.endswith("status?resource=interactionModel"):
                    return next(statuses)
                if method == "GET":
                    return expected_model
                return {}

        sleeps: list[float] = []
        Uploader(sleeper=sleeps.append).upload(
            "skill-id",
            "en-GB",
            self.ROOT / "en-GB.json",
            "hear service",
            "client-id",
            "client-secret",
            "refresh-token",
            30,
        )

        payload = next(call[2] for call in calls if call[0] == "PUT")
        assert payload["interactionModel"]["languageModel"]["intents"] == source[
            "interactionModel"
        ]["languageModel"]["intents"]
        assert payload["interactionModel"]["languageModel"]["types"] == source[
            "interactionModel"
        ]["languageModel"]["types"]
        assert sleeps == [5]

    def test_rejects_an_alexa_model_with_changed_slot_types(self):
        source = json.loads((self.ROOT / "en-GB.json").read_text(encoding="utf-8"))

        class Uploader(AlexaModelUploader):
            def _access_token(self, *args):
                return "access"

            def _wait_for_build(self, *args):
                return None

            def _request_json(self, method, url, payload, access_token, content_type="application/json"):
                if method == "GET":
                    source["interactionModel"]["languageModel"]["invocationName"] = (
                        "hear service"
                    )
                    source["interactionModel"]["languageModel"]["types"] = []
                    return source
                return {}

        try:
            Uploader().upload(
                "skill-id",
                "en-GB",
                self.ROOT / "en-GB.json",
                "hear service",
                "client-id",
                "client-secret",
                "refresh-token",
                30,
            )
        except RuntimeError as error:
            assert str(error) == "Alexa interaction-model types did not match en-GB.json"
        else:
            raise AssertionError("Expected slot-type verification to fail")
