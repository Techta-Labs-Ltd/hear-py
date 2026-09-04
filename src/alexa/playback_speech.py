from __future__ import annotations


class PlaybackSpeech:
    DEVELOPMENT_INVOCATION = "test development"
    PRODUCTION_INVOCATION = "Hear Service"
    GUIDE = (
        "While a recording is playing, say pause to keep your place, then resume to carry on. "
        "Say next or skip for the next recording, previous for the one before it, repeat or "
        "start over to return to the beginning, rewind 30 seconds, or fast forward 2 minutes. "
        "If you do not give a time, rewind and fast forward move by the standard step. You can "
        "say faster, slower, or normal speed. You can also choose first speed for 0.5 times, "
        "second for 0.75, third for normal speed, fourth for 1.25, fifth for 1.5, or sixth for "
        "2 times speed. Available speeds may vary by recording. Say stop when you want to "
        "finish listening. Loop and shuffle are not available."
    )
    CARD_SECTION = (
        "CONTROL PLAYBACK\n"
        "- Pause (keeps your place) / Resume.\n"
        "- Next or Skip / Previous.\n"
        "- Repeat / Start over.\n"
        "- Rewind 30 seconds / Fast forward 2 minutes.\n"
        "- Rewind / Fast forward (uses the standard step).\n"
        "- Faster / Slower / Normal speed.\n"
        "- First through sixth speed: 0.5x, 0.75x, 1x, 1.25x, 1.5x or 2x.\n"
        "- Stop (finishes listening).\n"
        "Loop and shuffle are not available."
    )
    SPEED_NOT_SUPPORTED = "This recording does not have faster or slower versions. I can only play it at normal speed."
    SPEED_MAX = "This is the maximum speed."
    SPEED_MIN = "This is the minimum speed."
    SPEED_INVALID = "Say first through sixth speed, normal speed, faster, or slower."
    QUEUE_FINISHED = "You've reached the end of these recordings. What would you like to listen to next?"
    PUBLICATION_QUEUE_FINISHED = "You've reached the end of this publication. What would you like to listen to next?"
    RESUMING = "Resuming where you left off."
    NOTHING_TO_RESUME = "Nothing to resume. Say what's trending, or play something to get started."
    PLAYING_NEXT = "Playing the next recording."
    PLAYING_PREVIOUS = "Playing the previous recording."
    REPLAYING = "Playing again from the start."
    NO_PREVIOUS = "There is no previous content to play."
    CANNOT_SEEK = "Nothing is playing right now. Say play to start listening."
    LOOP_SHUFFLE_UNAVAILABLE = "Looping and shuffle are not available on Hear yet. Say next, repeat, or pause."
    NO_TRACKS_AVAILABLE = "Welcome to Hear. There are no tracks available right now. Check back soon."

    @staticmethod
    def invocation(stage: str) -> str:
        return (
            PlaybackSpeech.PRODUCTION_INVOCATION
            if str(stage).strip().casefold() == "production"
            else PlaybackSpeech.DEVELOPMENT_INVOCATION
        )

    @staticmethod
    def mid_session_guide(stage: str) -> str:
        invocation = PlaybackSpeech.invocation(stage)
        return (
            "While audio is playing, you can pause it and then say, Alexa, ask "
            f"{invocation} to rate this content. To change the playback speed, say, Alexa, "
            f"ask {invocation} to play faster, play slower, or use normal speed."
        )

    @staticmethod
    def guide(stage: str) -> str:
        return f"{PlaybackSpeech.GUIDE} {PlaybackSpeech.mid_session_guide(stage)}"

    @staticmethod
    def card_section(stage: str) -> str:
        invocation = PlaybackSpeech.invocation(stage)
        return (
            f"{PlaybackSpeech.CARD_SECTION}\n"
            "WHILE AUDIO IS PLAYING\n"
            f"- Alexa, ask {invocation} to rate this content.\n"
            f"- Alexa, ask {invocation} to play faster.\n"
            f"- Alexa, ask {invocation} to play slower.\n"
            f"- Alexa, ask {invocation} to use normal speed."
        )

    @staticmethod
    def speed_unavailable(speed: float, available: str) -> str:
        return f"Speed {speed} is not available for this content. Available speeds are {available}."

    @staticmethod
    def speed_set(speed: float, *, idle: bool = False) -> str:
        message = (
            "Playback speed reset to normal."
            if speed == 1.0
            else f"Playback speed set to {speed}x."
        )
        return f"{message} What would you like to listen to next?" if idle else message

    @staticmethod
    def seek(direction: int, moved_ms: int, target_ms: int, duration_ms=None) -> str:
        if moved_ms <= 0:
            if direction < 0 and target_ms == 0:
                return "You are already at the beginning."
            if direction > 0 and isinstance(duration_ms, (int, float)):
                return "You are already at the end."
            return "I couldn't move the playback position."
        amount = PlaybackSpeech.duration(moved_ms)
        return f"Rewound {amount}." if direction < 0 else f"Skipped forward {amount}."

    @staticmethod
    def duration(milliseconds: int) -> str:
        seconds = max(1, round(milliseconds / 1000))
        if seconds % 3600 == 0:
            hours = seconds // 3600
            return f"{hours} {'hour' if hours == 1 else 'hours'}"
        if seconds % 60 == 0:
            minutes = seconds // 60
            return f"{minutes} {'minute' if minutes == 1 else 'minutes'}"
        return f"{seconds} {'second' if seconds == 1 else 'seconds'}"
