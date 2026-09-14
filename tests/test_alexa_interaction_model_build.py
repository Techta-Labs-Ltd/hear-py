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
        assert len(types["HEAR_TOPIC"]) == 4_562
        assert len(types["HEAR_DISCOVERY"]) >= 10_000
        locations = {item["name"]["value"] for item in types["HEAR_LOCATION"]}
        assert {"Liverpool", "Sevenoaks", "Dorking"}.issubset(locations)
        discovery = {item["name"]["value"] for item in types["HEAR_DISCOVERY"]}
        assert {
            "Liverpool",
            "Sevenoaks",
            "Talking News Federation",
            "Premier League",
        }.issubset(discovery)
        assert "Adeshina Ayomide" not in discovery
        discovery_by_name = {
            item["name"]["value"]: item["name"] for item in types["HEAR_DISCOVERY"]
        }
        assert "premiership" in discovery_by_name["Premier League"]["synonyms"]
        assert {
            "talk en news federation",
            "TNF",
            "T. N. F.",
            "tee en eff",
        }.issubset(discovery_by_name["Talking News Federation"]["synonyms"])
        assert "swidon" not in discovery_by_name["Swindon"].get("synonyms", [])
        assert "Andover" not in discovery_by_name["Andover Talking Newspaper"].get("synonyms", [])
        topics_by_name = {
            item["name"]["value"]: item["name"] for item in types["HEAR_TOPIC"]
        }
        assert "sports" not in {
            synonym.casefold()
            for synonym in topics_by_name["Sport"].get("synonyms", [])
        }
        assert "Sports" in topics_by_name

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
        AlexaInteractionModelBuilder.write(
            self.ROOT / "en-GB.json",
            self.ROOT / "alexa-slot-imports",
            output,
        )

        assert output.stat().st_size <= AlexaInteractionModelBuilder.MAX_MODEL_BYTES
        assert json.loads(output.read_text(encoding="utf-8")) == self._model()
