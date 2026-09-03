class PlaybackConstants:
    CONTROLLER_REQUESTS = {
        "PAUSE": "PlaybackController.PauseCommandIssued",
        "PLAY": "PlaybackController.PlayCommandIssued",
        "NEXT": "PlaybackController.NextCommandIssued",
        "PREVIOUS": "PlaybackController.PreviousCommandIssued",
    }
    ACTIVE_PLAYBACK_STATUSES = frozenset({"starting", "playing", "paused"})
    TRANSPORT_INTENTS = frozenset(
        {
            "AMAZON.NextIntent",
            "AMAZON.SkipIntent",
            "AMAZON.PreviousIntent",
            "AMAZON.PauseIntent",
            "AMAZON.ResumeIntent",
            "AMAZON.RepeatIntent",
            "AMAZON.StartOverIntent",
            "SetPlaybackSpeedIntent",
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
            "RewindIntent",
            "FastForwardIntent",
        }
    )
    TRANSPORT_REQUEST_TYPES = frozenset(CONTROLLER_REQUESTS.values())
    USER_PLAYBACK_EVENT_TYPES = {
        "CANCELLED": "cancelled",
    }
