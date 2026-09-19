from __future__ import annotations

import json
from pathlib import Path

from scripts.build_alexa_interaction_model import AlexaInteractionModelBuilder


class TestAlexaInteractionModelBuild:
    ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def _model(cls) -> dict:
        return AlexaInteractionModelBuilder.build(cls.ROOT / "en-GB.json")

    def test_deployment_model_retains_only_curated_slot_values(self):
        types = {
            item["name"]: item["values"]
            for item in self._model()["interactionModel"]["languageModel"]["types"]
        }

        assert {
            slot_name: len(types[slot_name])
            for slot_name in (
                "HEAR_LOCATION",
                "HEAR_ORGANIZATION",
                "HEAR_TOPIC",
                "HEAR_DISCOVERY",
            )
        } == {
            "HEAR_LOCATION": 3,
            "HEAR_ORGANIZATION": 3,
            "HEAR_TOPIC": 3,
            "HEAR_DISCOVERY": 4,
        }

    def test_deployment_model_keeps_search_query_carrier_based(self):
        interaction_model = self._model()["interactionModel"]
        intents = {item["name"]: item for item in interaction_model["languageModel"]["intents"]}
        dialog_intents = {item["name"]: item for item in interaction_model["dialog"]["intents"]}

        search = intents["SearchContentIntent"]
        assert search["slots"] == [{"name": "searchQuery", "type": "AMAZON.SearchQuery"}]
        assert search["samples"] == [
            "play {searchQuery}",
            "find {searchQuery}",
            "listen to {searchQuery}",
            "play content on {searchQuery}",
            "play content from {searchQuery}",
            "content on {searchQuery}",
            "content from {searchQuery}",
        ]
        assert "SearchContentIntent" not in dialog_intents
        assert dialog_intents["CarrierlessDiscoveryIntent"]["slots"][0]["type"] == (
            "HEAR_DISCOVERY"
        )
        assert intents["OpenDiscoveryIntent"]["slots"] == [
            {
                "name": "searchQuery",
                "type": "AMAZON.SearchQuery",
                "samples": ["{searchQuery}"],
            }
        ]
        assert dialog_intents["OpenDiscoveryIntent"]["slots"][0]["type"] == (
            "AMAZON.SearchQuery"
        )

    def test_compact_deployment_model_fits_alexa_limit(self, tmp_path):
        output = tmp_path / "en-GB.json"
        AlexaInteractionModelBuilder.write(self.ROOT / "en-GB.json", output)

        assert output.stat().st_size <= AlexaInteractionModelBuilder.MAX_MODEL_BYTES
        assert json.loads(output.read_text(encoding="utf-8")) == self._model()

    def test_production_model_changes_only_the_invocation_name(self):
        development_model = self._model()
        production_model = AlexaInteractionModelBuilder.build(
            self.ROOT / "en-GB.json",
            "hear service",
        )

        assert development_model["interactionModel"]["languageModel"]["invocationName"] == (
            "test development"
        )
        assert production_model["interactionModel"]["languageModel"]["invocationName"] == (
            "hear service"
        )
        assert production_model["interactionModel"]["languageModel"]["intents"] == (
            development_model["interactionModel"]["languageModel"]["intents"]
        )
        assert production_model["interactionModel"]["languageModel"]["types"] == (
            development_model["interactionModel"]["languageModel"]["types"]
        )
