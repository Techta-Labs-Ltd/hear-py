from pathlib import Path

from src.models.playback_control_policy import PlaybackControlPolicy


class TestPlaybackControlPolicy:
    def test_speed_decisions_validate_variants_and_playback_state(self) -> None:
        store = {
            "currentPlaybackSpeeds": [
                {"speed": 1.0, "audioUrl": "https://example.test/normal.mp3"},
                {"speed": 1.5, "audioUrl": "https://example.test/fast.mp3"},
            ]
        }
        unavailable = PlaybackControlPolicy.apply_speed(
            None, store, 1.25, default_speed=1.0
        )
        idle = PlaybackControlPolicy.apply_speed(None, store, 1.0, default_speed=1.0)
        restart = PlaybackControlPolicy.apply_speed(
            {"status": "playing", "offsetMs": 4000}, store, 1.5, default_speed=1.0
        )

        assert (unavailable.kind, unavailable.available_speeds) == ("unavailable", (1.0, 1.5))
        assert (idle.kind, idle.speed) == ("idle", 1.0)
        assert (restart.kind, restart.offset_ms) == ("restart", 4000)

    def test_step_and_seek_decisions_enforce_limits_without_platform_input(self) -> None:
        store = {
            "playbackSpeed": 1.5,
            "currentPlaybackSpeeds": [
                {"speed": 1.0, "audioUrl": "https://example.test/normal.mp3"},
                {"speed": 1.5, "audioUrl": "https://example.test/fast.mp3"},
            ],
        }
        at_limit = PlaybackControlPolicy.step_speed(
            {"status": "paused"}, store, "up", default_speed=1.0
        )
        seek = PlaybackControlPolicy.seek(
            {"offsetMs": 59_500, "durationMs": 60_000}, 1, 30_000
        )

        assert at_limit.kind == "limit"
        assert (seek.kind, seek.offset_ms, seek.moved_ms) == ("restart", 59_000, 500)

    def test_policy_has_no_platform_dependency(self) -> None:
        source = (
            Path(__file__).parents[1] / "src/models/playback_control_policy.py"
        ).read_text(encoding="utf-8")
        assert "src.alexa" not in source
        assert "handler_input" not in source
