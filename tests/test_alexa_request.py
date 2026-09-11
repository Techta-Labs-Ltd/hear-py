from __future__ import annotations

import pytest

from src.alexa.request import AlexaRequest


class TestAlexaDiscoverySlotSelection:
    @staticmethod
    def _slot(
        value: str | None,
        code: str | None = None,
        matches: list[str] | None = None,
    ) -> dict:
        slot = {"value": value}
        if code:
            slot["resolutions"] = {
                "resolutionsPerAuthority": [
                    {
                        "status": {"code": code},
                        "values": [{"value": {"name": match}} for match in (matches or [])],
                    }
                ]
            }
        return slot

    def test_unique_match_uses_canonical_and_retains_spoken_value(self):
        selection = AlexaRequest.get_discovery_slot_selection(
            self._slot("tnf", "ER_SUCCESS_MATCH", ["Talking News Federation"])
        )

        assert selection == {
            "spoken": "tnf",
            "canonical": "Talking News Federation",
            "effective": "Talking News Federation",
            "matches": ["Talking News Federation"],
            "statuses": ["ER_SUCCESS_MATCH"],
            "ambiguous": False,
        }

    @pytest.mark.parametrize("code", ["ER_SUCCESS_NO_MATCH", "ER_ERROR_TIMEOUT", None])
    def test_no_usable_match_uses_captured_value(self, code):
        selection = AlexaRequest.get_discovery_slot_selection(self._slot("New Local Voice", code))

        assert selection["spoken"] == "New Local Voice"
        assert selection["canonical"] is None
        assert selection["effective"] == "New Local Voice"

    def test_multiple_matches_preserve_spoken_value_for_resolver_ambiguity(self):
        selection = AlexaRequest.get_discovery_slot_selection(
            self._slot("reading", "ER_SUCCESS_MATCH", ["Reading", "Reading News"])
        )

        assert selection["canonical"] is None
        assert selection["effective"] == "reading"
        assert selection["ambiguous"] is True

    def test_match_without_usable_canonical_uses_captured_value(self):
        selection = AlexaRequest.get_discovery_slot_selection(
            self._slot("New Voice", "ER_SUCCESS_MATCH", ["   "])
        )

        assert selection["effective"] == "New Voice"
