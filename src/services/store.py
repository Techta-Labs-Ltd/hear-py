from __future__ import annotations

DEFAULT_STORE: dict[str, object] = {
    "activeDialog": None,
    "locality": None,
    "lastToken": None,
    "lastOffsetMs": 0,
    "playbackSpeed": 1.0,
    "awaitingFeedback": False,
    "awaitingFollow": False,
    "awaitingReportDecision": False,
    "reportContext": None,
    "pendingFeedback": None,
    "feedbackCandidates": [],
    "publicationFeedbackProgress": {},
    "answeredFeedbackKeys": [],
    "feedbackHistory": [],
    "reportHistory": [],
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
    "deviceId": None,
    "listeningPattern": {},
    "playCount": 0,
    "playHistory": [],
    "followedCreators": [],
    "pendingFollowSource": None,
    "latitude": None,
    "longitude": None,
    "localityResolvedAt": None,
    "userName": None,
    "userEmail": None,
    "userAddress": None,
    "givenName": None,
    "fullName": None,
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
    "feedbackReminderAlertToken": None,
    "feedbackAskedForToken": None,
    "feedbackAskedTokens": [],
    "feedbackGivenTokens": [],
    "playbackDurationEstimateMs": None,
    "userCity": None,
    "userState": None,
    "userCountry": None,
    "currentPlaybackSpeeds": None,
    "playbackQueue": None,
    "preparedNextContent": None,
    "browseQueueItems": None,
    "activePlayback": None,
    "awaitingResume": False,
    "launchCount": 0,
    "firstLaunchedAt": None,
    "lastLaunchedAt": None,
    "listModeActive": False,
    "listenerId": None,
    "alexaUserId": None,
    "onboardingComplete": False,
    "onboardingStage": None,
    "onboardingRetries": 0,
    "onboardingTownAttempts": 0,
    "onboardingTownResolverFailures": 0,
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
    "lastCompletedSource": None,
    "pendingLatestSource": None,
    "lastLatestSourceOfferContentId": None,
}


class SessionStore:
    __slots__ = ()

    @staticmethod
    def get(handler_input) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        return dict(attrs.get("_store") or DEFAULT_STORE)

    @staticmethod
    def update(handler_input, updates: dict) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        store = {**(attrs.get("_store") or DEFAULT_STORE), **updates}
        attrs["_store"] = store
        attrs["_dirty"] = True
        handler_input.attributes_manager.request_attributes = attrs
        return store


_store = SessionStore()
get_store = _store.get
update_store = _store.update
