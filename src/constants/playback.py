class PlaybackConstants:
    CONTROLLER_REQUESTS = {
        "PAUSE": "PlaybackController.PauseCommandIssued",
        "PLAY": "PlaybackController.PlayCommandIssued",
        "NEXT": "PlaybackController.NextCommandIssued",
        "PREVIOUS": "PlaybackController.PreviousCommandIssued",
    }
    ACTIVE_PLAYBACK_STATUSES = frozenset({"starting", "playing", "paused"})
    USER_PLAYBACK_EVENT_TYPES = {
        "USER_STOPPED": "user_stopped",
        "PAUSED": "paused",
        "RESUMED": "resumed",
        "CANCELLED": "cancelled",
    }
