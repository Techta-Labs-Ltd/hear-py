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

        assert (unavailable.kind, unavailable.speed) == ("idle", 1.25)
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
        assert (seek.kind, seek.offset_ms, seek.moved_ms) == ("boundary", 59_500, 0)

    def test_seek_direction_never_reverses(self) -> None:
        forward = PlaybackControlPolicy.seek(
            {"offsetMs": 120_000, "durationMs": 300_000}, 1, 15_000
        )
        rewind = PlaybackControlPolicy.seek(
            {"offsetMs": 120_000, "durationMs": 300_000}, -1, 15_000
        )
        start = PlaybackControlPolicy.seek(
            {"offsetMs": 5_000, "durationMs": 300_000}, -1, 15_000
        )

        assert (forward.kind, forward.offset_ms, forward.moved_ms) == (
            "restart",
            135_000,
            15_000,
        )
        assert (rewind.kind, rewind.offset_ms, rewind.moved_ms) == (
            "restart",
            105_000,
            15_000,
        )
        assert (start.kind, start.offset_ms, start.moved_ms) == (
            "restart",
            0,
            5_000,
        )

    def test_seek_overrun_is_explicit_and_direction_safe(self) -> None:
        forward = PlaybackControlPolicy.seek(
            {"offsetMs": 120_000, "durationMs": 300_000}, 1, 1_800_000
        )
        rewind = PlaybackControlPolicy.seek(
            {"offsetMs": 120_000, "durationMs": 300_000}, -1, 1_800_000
        )

        assert forward.kind == "restart"
        assert forward.offset_ms == 299_000
        assert forward.moved_ms == 179_000
        assert forward.requested_ms == 1_800_000
        assert forward.available_ms == 180_000
        assert forward.limited is True

        assert rewind.kind == "restart"
        assert rewind.offset_ms == 0
        assert rewind.moved_ms == 120_000
        assert rewind.requested_ms == 1_800_000
        assert rewind.available_ms == 120_000
        assert rewind.limited is True

    def test_idle_step_speed_changes_listener_default_without_track_variants(self) -> None:
        faster = PlaybackControlPolicy.step_speed(
            None, {"playbackSpeed": 1.0}, "up", default_speed=1.0
        )
        slower = PlaybackControlPolicy.step_speed(
            None, {"playbackSpeed": 1.0}, "down", default_speed=1.0
        )

        assert faster.kind == "idle"
        assert faster.speed > 1.0
        assert slower.kind == "idle"
        assert slower.speed < 1.0

    def test_policy_has_no_platform_dependency(self) -> None:
        source = (
            Path(__file__).parents[1] / "src/models/playback_control_policy.py"
        ).read_text(encoding="utf-8")
        assert "src.alexa" not in source
        assert "handler_input" not in source
