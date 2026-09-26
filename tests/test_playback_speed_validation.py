from src.utils.playback import PlaybackUtils


def test_named_and_numeric_playback_speeds_are_exact():
    assert PlaybackUtils.normalise_speed("first speed") == 0.75
    assert PlaybackUtils.normalise_speed("second") == 1.0
    assert PlaybackUtils.normalise_speed("normal speed") == 1.0
    assert PlaybackUtils.normalise_speed("third") == 1.25
    assert PlaybackUtils.normalise_speed("one and a half") == 1.5
    assert PlaybackUtils.normalise_speed("double speed") == 2.0
    assert PlaybackUtils.normalise_speed("1.25") == 1.25


def test_unsupported_playback_speed_is_not_snapped():
    assert PlaybackUtils.normalise_speed("1.4") is None
    assert PlaybackUtils.normalise_speed("0.5") is None
    assert PlaybackUtils.normalise_speed("half speed") is None
    assert PlaybackUtils.normalise_speed("seventh speed") is None
    assert PlaybackUtils.normalise_speed(None) is None


def test_removed_speed_is_not_used_for_selection_or_playback():
    variants = [
        {"speed": 0.5, "audioUrl": "https://example.test/half.mp3"},
        {"speed": 0.75, "audioUrl": "https://example.test/three-quarters.mp3"},
        {"speed": 1.0, "audioUrl": "https://example.test/normal.mp3"},
    ]

    assert PlaybackUtils.get_next_speed(variants, 0.75, "down") is None
    assert PlaybackUtils.resolve_effective_speed(0.5, variants) == 1.0
