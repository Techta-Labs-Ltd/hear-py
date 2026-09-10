from __future__ import annotations

import json
from pathlib import Path

from scripts.build_alexa_interaction_model import AlexaInteractionModelBuilder


class TestAlexaInteractionModelBuild:
    ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def _model(cls) -> dict:
        return AlexaInteractionModelBuilder.build(
            cls.ROOT / "en-GB.json",
            cls.ROOT / "alexa-slot-imports",
        )

    def test_deployment_model_contains_all_generated_domain_values(self):
        types = {
            item["name"]: item["values"]
            for item in self._model()["interactionModel"]["languageModel"]["types"]
        }

        assert len(types["HEAR_LOCATION"]) == 5_429
        assert len(types["HEAR_ORGANIZATION"]) == 286
        assert len(types["HEAR_CREATOR"]) == 14
        assert len(types["HEAR_TOPIC"]) == 4_562
        locations = {item["name"]["value"] for item in types["HEAR_LOCATION"]}
        assert {"Liverpool", "Sevenoaks", "Dorking"}.issubset(locations)

    def test_deployment_model_keeps_search_query_carrier_based(self):
        interaction_model = self._model()["interactionModel"]
        intents = {
            item["name"]: item
            for item in interaction_model["languageModel"]["intents"]
        }
        dialog_intents = {
            item["name"] for item in interaction_model["dialog"]["intents"]
        }

        search = intents["SearchContentIntent"]
        assert search["slots"] == [
            {"name": "searchQuery", "type": "AMAZON.SearchQuery"}
        ]
        assert search["samples"] == [
            "play {searchQuery}",
            "find {searchQuery}",
            "listen to {searchQuery}",
        ]
        assert "SearchContentIntent" not in dialog_intents

    def test_compact_deployment_model_fits_alexa_limit(self, tmp_path):
        output = tmp_path / "en-GB.json"
        AlexaInteractionModelBuilder.write(
            self.ROOT / "en-GB.json",
            self.ROOT / "alexa-slot-imports",
            output,
        )

        assert output.stat().st_size <= AlexaInteractionModelBuilder.MAX_MODEL_BYTES
        assert json.loads(output.read_text(encoding="utf-8")) == self._model()
