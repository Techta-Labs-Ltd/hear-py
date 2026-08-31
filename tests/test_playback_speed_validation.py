from src.utils.playback import PlaybackUtils


def test_named_and_numeric_playback_speeds_are_exact():
    assert PlaybackUtils.normalise_speed("first speed") == 0.5
    assert PlaybackUtils.normalise_speed("second") == 0.75
    assert PlaybackUtils.normalise_speed("normal speed") == 1.0
    assert PlaybackUtils.normalise_speed("fourth") == 1.25
    assert PlaybackUtils.normalise_speed("one and a half") == 1.5
    assert PlaybackUtils.normalise_speed("double speed") == 2.0
    assert PlaybackUtils.normalise_speed("1.25") == 1.25


def test_unsupported_playback_speed_is_not_snapped():
    assert PlaybackUtils.normalise_speed("1.4") is None
    assert PlaybackUtils.normalise_speed("seventh speed") is None
    assert PlaybackUtils.normalise_speed(None) is None
