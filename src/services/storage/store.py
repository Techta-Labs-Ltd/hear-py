"""Low-level session-store primitives.

This is a leaf module: it depends only on configuration, never on other
project modules. Higher-level modules (persistence, alexa_reminders,
publication_tracks, …) build on top of it, so keeping the store accessors
here lets those modules share the primitives without importing the whole
``persistence`` module and creating an import cycle.
"""
from __future__ import annotations

DEFAULT_STORE: dict[str, object] = {
    "activeDialog": None,
    "locality": None,
    "lastToken": None,
    "lastOffsetMs": 0,
    "playbackSpeed": 1.0,
    "awaitingFeedback": False,
    "awaitingFollow": False,
    "awaitingNotificationOptIn": False,
    "awaitingReportDecision": False,
    "reportContext": None,
    "pendingFeedback": None,
    "feedbackCandidates": [],
    "answeredFeedbackKeys": [],
    "feedbackContentId": None,
    "feedbackCategory": None,
    "feedbackCreator": None,
    "feedbackCreatorId": None,
    "feedbackContentTitle": None,
    "feedbackPromptText": None,
    "currentContentId": None,
    "currentContentTitle": None,
    "currentCreator": None,
    "currentCreatorId": None,
    "currentCategory": None,
    "notificationsEnabled": False,
    "deviceId": None,
    "listeningPattern": {},
    "playCount": 0,
    "playHistory": [],
    "followedCreators": [],
    "latitude": None,
    "longitude": None,
    "localityResolvedAt": None,
    "userName": None,
    "userEmail": None,
    "userAddress": None,
    "givenName": None,
    "familyName": None,
    "fullName": None,
    "profilePermissionRequested": False,
    "listenerProfileResolvedAt": None,
    "listenerProfileSkipUntil": None,
    "browseCatalog": None,
    "currentSummary": None,
    "launchBrowseIds": None,
    "pendingDiscoveryIntent": None,
    "pendingDiscoveryCategory": None,
    "pendingBrowseItems": None,
    "devicePostalCode": None,
    "deviceCountryCode": None,
    "awaitingContinueAfterFlag": False,
    "showHomeBrowseOnNextLaunch": False,
    "feedbackReminderAlertToken": None,
    "feedbackAskedForToken": None,
    "feedbackAskedTokens": [],
    "feedbackGivenTokens": [],
    "playbackDurationEstimateMs": None,
    "pendingLocalContentRequest": False,
    "userCity": None,
    "userState": None,
    "userCountry": None,
    "pendingCityCapture": False,
    "currentPlaybackSpeeds": None,
    "playbackQueue": None,
    "preparedNextContent": None,
    "browseQueueItems": None,
    "activePlayback": None,
    "awaitingResume": False,
    "lastPlayStartedAt": None,
    "lastPlayContentId": None,
    "currentDurationSecs": None,
    "currentAudioUrl": None,
    "suppressNextStoppedEvent": False,
    "suppressNextStartedEvent": False,
    "launchCount": 0,
    "firstLaunchedAt": None,
    "lastLaunchedAt": None,
    "listModeActive": False,
    "listPosition": 0,
    "pendingNotificationQueue": None,
    "awaitingNotificationChoice": False,
    "_announcedInSession": [],
    "listenerId": None,
    "onboardingComplete": False,
    "onboardingStage": None,
    "onboardingRetries": 0,
    "onboardingTownAttempts": 0,
    "pendingLocationConfirm": None,
    "awaitingLocationConfirm": False,
    "awaitingCommunityPlayback": False,
    "locationSource": None,
    "awaitingSearchConfirmation": False,
    "pendingResolution": None,
    "pendingAmbiguity": None,
    "pendingSuggestions": [],
    "suggestionIndex": 0,
    "excludedSuggestions": [],
}


def get_store(handler_input) -> dict:
    """Return a shallow copy of the current persistence store from request attributes."""
    attrs = handler_input.attributes_manager.request_attributes
    return dict(attrs.get("_store") or DEFAULT_STORE)


def update_store(handler_input, updates: dict) -> dict:
    """Merge *updates* into the persistence store, mark dirty, and return the new store."""
    attrs = handler_input.attributes_manager.request_attributes
    store = {**(attrs.get("_store") or DEFAULT_STORE), **updates}
    attrs["_store"] = store
    attrs["_dirty"] = True
    handler_input.attributes_manager.request_attributes = attrs
    return store
