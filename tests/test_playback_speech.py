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
        "first through fifth speed",
        "first for 0.75 times",
        "fifth for 2 times speed",
        "stop",
        "loop",
        "shuffle",
    ):
        assert command in guide


def test_seek_speech_uses_natural_uk_english_durations():
    assert PlaybackSpeech.seek(-1, 30_000, 20_000) == "Going back 30 seconds."
    assert PlaybackSpeech.seek(1, 120_000, 150_000) == "Skipping ahead 2 minutes."
    assert PlaybackSpeech.seek(-1, 1_000, 0) == "Going back 1 second."


def test_seek_speech_explains_requested_jump_beyond_track():
    assert PlaybackSpeech.seek(
        1,
        179_000,
        299_000,
        300_000,
        requested_ms=1_800_000,
        available_ms=180_000,
        limited=True,
    ) == "This recording only has 3 minutes left, so I'll skip to the end."
    assert PlaybackSpeech.seek(
        -1,
        120_000,
        0,
        300_000,
        requested_ms=1_800_000,
        available_ms=120_000,
        limited=True,
    ) == "You're only 2 minutes into this recording, so I'll go back to the beginning."


def test_seek_duration_speaks_mixed_units_naturally():
    assert PlaybackSpeech.duration(179_000) == "2 minutes and 59 seconds"
    assert PlaybackSpeech.duration(3_661_000) == "1 hour, 1 minute and 1 second"


def test_seek_speech_explains_playback_boundaries():
    assert PlaybackSpeech.seek(-1, 0, 0) == "You're already at the beginning."
    assert PlaybackSpeech.seek(1, 0, 59_000, 60_000) == "You're already at the end."


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
