from __future__ import annotations


class AvailabilityConstants:
    DIALOG_TYPE = "availability"
    SOURCE_KIND = "source"
    LOCATION_KIND = "location"
    FORMAT_KIND = "format"
    PUBLICATION_KIND = "publication"
    TRACK_KIND = "track"
    MORE_INTENTS = frozenset({"ShowMoreBrowseIntent", "AMAZON.NextIntent"})
    PREVIOUS_INTENTS = frozenset({"ShowPreviousBrowseIntent", "AMAZON.PreviousIntent"})
    EXIT_INTENTS = frozenset({"AMAZON.CancelIntent", "AMAZON.StopIntent"})
    LOCATION_FILTER_KEYS = frozenset({"city", "countryCode", "latitude", "longitude"})
