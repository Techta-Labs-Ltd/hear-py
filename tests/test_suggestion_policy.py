from pathlib import Path

from src.models.suggestion_policy import SuggestionPolicy


class TestSuggestionPolicy:
    def test_maps_content_suggestions_to_explicit_action_and_slots(self) -> None:
        decision = SuggestionPolicy.decide(
            {"pendingNlpSuggestion": [{"intent": "publication", "query": "weekly news"}]}
        )

        assert decision.kind == "action"
        assert decision.action == "play_content"
        assert decision.intent == "publication"
        assert decision.slots["searchPlan"]["filter"] == {"isPublication": True}

    def test_maps_browse_and_feedback_suggestions_without_platform_state(self) -> None:
        browse = SuggestionPolicy.decide(
            {"pendingNlpSuggestion": [{"intent": "show_more"}]}
        )
        feedback = SuggestionPolicy.decide(
            {
                "awaitingFeedback": True,
                "pendingNlpSuggestion": [{"intent": "feedback_enjoyed"}],
            }
        )

        assert (browse.kind, browse.action, browse.intent) == ("action", "browse_more", None)
        assert (feedback.kind, feedback.action) == ("feedback", "feedback_enjoyed")

    def test_lost_and_unknown_suggestions_are_explicit(self) -> None:
        assert SuggestionPolicy.decide({}).kind == "lost"
        assert (
            SuggestionPolicy.decide(
                {"pendingNlpSuggestion": [{"intent": "unrecognized"}]}
            ).kind
            == "unknown"
        )

    def test_policy_has_no_platform_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/models/suggestion_policy.py").read_text(
            encoding="utf-8"
        )
        assert "src.alexa" not in source
        assert "handler_input" not in source
