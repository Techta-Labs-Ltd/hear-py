from src.alexa.playback_speech import PlaybackSpeech


def test_playback_guide_covers_every_supported_control():
    guide = PlaybackSpeech.GUIDE.casefold()
    for command in (
        "pause",
        "resume",
        "next",
        "skip",
        "previous",
        "repeat",
        "start over",
        "rewind",
        "fast forward",
        "faster",
        "slower",
        "normal speed",
        "first through sixth speed",
        "stop",
        "loop",
        "shuffle",
    ):
        assert command in guide


def test_seek_speech_uses_natural_uk_english_durations():
    assert PlaybackSpeech.seek(-1, 30_000, 20_000) == "Rewound 30 seconds."
    assert PlaybackSpeech.seek(1, 120_000, 150_000) == "Skipped forward 2 minutes."
    assert PlaybackSpeech.seek(-1, 1_000, 0) == "Rewound 1 second."


def test_seek_speech_explains_playback_boundaries():
    assert PlaybackSpeech.seek(-1, 0, 0) == "You are already at the beginning."
    assert PlaybackSpeech.seek(1, 0, 59_000, 60_000) == "You are already at the end."


def test_development_mid_session_commands_use_the_development_invocation():
    guide = PlaybackSpeech.mid_session_guide("development")

    assert "Alexa, ask test development to rate this content" in guide
    assert "Alexa, ask test development to play faster" in guide
    assert "Hear Service" not in guide


def test_production_mid_session_commands_use_the_live_invocation():
    guide = PlaybackSpeech.mid_session_guide("production")

    assert "Alexa, ask Hear Service to rate this content" in guide
    assert "Alexa, ask Hear Service to play faster" in guide
    assert "test development" not in guide


def test_runtime_playback_messages_are_owned_by_playback_speech():
    assert PlaybackSpeech.PLAYING_NEXT == "Playing the next recording."
    assert PlaybackSpeech.PLAYING_PREVIOUS == "Playing the previous recording."
    assert PlaybackSpeech.REPLAYING == "Playing again from the start."
    assert PlaybackSpeech.NOTHING_TO_RESUME.startswith("Nothing to resume")
    assert PlaybackSpeech.QUEUE_FINISHED.startswith("You've reached the end")


def test_playback_speed_messages_cover_active_and_idle_sessions():
    assert PlaybackSpeech.speed_set(1.0) == "Playback speed reset to normal."
    assert PlaybackSpeech.speed_set(1.5) == "Playback speed set to 1.5x."
    assert PlaybackSpeech.speed_set(1.5, idle=True).endswith(
        "What would you like to listen to next?"
    )
    assert PlaybackSpeech.speed_unavailable(2.0, "1.0x, 1.5x") == (
        "Speed 2.0 is not available for this content. "
        "Available speeds are 1.0x, 1.5x."
    )
