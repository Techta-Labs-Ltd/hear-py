from pathlib import Path

from src.models.launch_policy import LaunchPolicy


class TestLaunchPolicy:
    def test_protected_decisions_preserve_priority(self) -> None:
        town = LaunchPolicy.protected(
            {"onboardingStage": "confirm_town_for_community", "awaitingContinueAfterFlag": True}
        )
        continue_after_flag = LaunchPolicy.protected({"awaitingContinueAfterFlag": True})

        assert town.kind == "town_capture"
        assert continue_after_flag.kind == "continue_after_flag"

    def test_pending_decisions_preserve_playback_and_feedback_priority(self) -> None:
        store = {
            "userName": "Ada",
            "awaitingFeedback": True,
            "pendingFeedback": {"subjectId": "content-1"},
            "feedbackContentTitle": "A title",
        }

        assert LaunchPolicy.pending(store, has_unfinished_playback=True).kind == "unfinished_playback"
        assert LaunchPolicy.pending(store, has_unfinished_playback=False).kind == "pending_feedback"
        assert (
            LaunchPolicy.pending(
                {"awaitingFeedback": True, "feedbackPromptText": "Rate this"},
                has_unfinished_playback=False,
            ).kind
            == "ask_pending_feedback"
        )

    def test_welcome_decision_classifies_first_and_returning_users(self) -> None:
        first_with_city = LaunchPolicy.welcome({"userName": "Ada", "userCity": "Leeds"})
        first_without_city = LaunchPolicy.welcome({"fullName": "Ada"})
        returning = LaunchPolicy.welcome({"playCount": 1, "locality": "York"})

        assert (first_with_city.kind, first_with_city.user_name, first_with_city.city) == (
            "first_with_city",
            "Ada",
            "Leeds",
        )
        assert first_without_city.kind == "first_without_city"
        assert (returning.kind, returning.locality) == ("returning", "York")

    def test_policy_has_no_platform_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/models/launch_policy.py").read_text(
            encoding="utf-8"
        )
        assert "src.alexa" not in source
        assert "handler_input" not in source
