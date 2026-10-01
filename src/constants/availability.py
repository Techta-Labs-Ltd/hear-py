from __future__ import annotations


class AvailabilityConstants:
    # Publication playback is not a three-choice voice list. Load a large
    # ordered track page so Alexa can enqueue the full edition continuously;
    # PlaybackQueue still lazy-loads further pages when a publication exceeds this cap.
    PUBLICATION_PLAYBACK_PAGE_SIZE = 100
    DIALOG_TYPE = "availability"
    SOURCE_KIND = "source"
    LOCATION_KIND = "location"
    FORMAT_KIND = "format"
    PUBLICATION_KIND = "publication"
    TRACK_KIND = "track"
    MORE_INTENTS = frozenset({"ShowMoreBrowseIntent", "AMAZON.NextIntent"})
    PREVIOUS_INTENTS = frozenset({"ShowPreviousBrowseIntent", "AMAZON.PreviousIntent"})
    EXIT_INTENTS = frozenset({"AMAZON.CancelIntent", "AMAZON.StopIntent"})
    PASSTHROUGH_INTENTS = frozenset(
        {
            "RateContentIntent",
            "ReportContentIntent",
            "ReportCreatorIntent",
            "SetPlaybackSpeedIntent",
            "IncreaseSpeedIntent",
            "DecreaseSpeedIntent",
        }
    )
    LOCATION_FILTER_KEYS = frozenset({"city", "countryCode", "latitude", "longitude"})
