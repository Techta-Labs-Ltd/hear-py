from __future__ import annotations

from copy import deepcopy


class StateSchema:
    SCHEMA_VERSION = 2
    CORE_SCOPE = "CORE"
    PLAYBACK_SCOPE = "PLAYBACK"
    DIALOG_SCOPE = "DIALOG"
    CACHE_SCOPE = "CACHE"
    SCOPES = (CORE_SCOPE, PLAYBACK_SCOPE, DIALOG_SCOPE, CACHE_SCOPE)
    # These are transitional projections of ``activeDialog`` for the few
    # Alexa-bound adapters which have not yet moved to the dialogue command
    # API.  The state contract owns the mapping so hydration and runtime
    # dialogue handling cannot silently drift apart.
    DIALOG_LEGACY_FLAGS = {
        "search_confirmation": "awaitingSearchConfirmation",
        "feedback": "awaitingFeedback",
        "report_decision": "awaitingReportDecision",
        "resume": "awaitingResume",
        "notification": "awaitingNotificationChoice",
        "organization_name": "awaitingOrganizationName",
        "publication_source": "awaitingPublicationSource",
        "feedback_continuation": "awaitingFeedbackContinuation",
    }
    FIELD_SPECS: dict[str, tuple[object, str | None]] = {
        "activeDialog": (None, DIALOG_SCOPE),
        "locality": (None, CORE_SCOPE),
        "lastToken": (None, None),
        "lastOffsetMs": (0, None),
        "playbackSpeed": (1.0, CORE_SCOPE),
        "awaitingFeedback": (False, DIALOG_SCOPE),
        "awaitingFeedbackContinuation": (False, DIALOG_SCOPE),
        "feedbackContinuation": (None, DIALOG_SCOPE),
        "awaitingOrganizationName": (False, DIALOG_SCOPE),
        "awaitingPublicationSource": (False, DIALOG_SCOPE),
        "awaitingFollow": (False, DIALOG_SCOPE),
        "awaitingNotificationChoice": (False, DIALOG_SCOPE),
        "pendingNotification": (None, DIALOG_SCOPE),
        "notificationPlayback": (None, PLAYBACK_SCOPE),
        "awaitingReportDecision": (False, DIALOG_SCOPE),
        "reportContext": (None, DIALOG_SCOPE),
        "pendingFeedback": (None, DIALOG_SCOPE),
        "feedbackCandidates": ([], None),
        "publicationFeedbackProgress": ({}, None),
        "answeredFeedbackKeys": ([], None),
        "feedbackContentId": (None, None),
        "feedbackCategory": (None, None),
        "feedbackCreator": (None, None),
        "feedbackCreatorId": (None, None),
        "feedbackContentTitle": (None, None),
        "feedbackPromptText": (None, None),
        "currentContentId": (None, None),
        "currentContentTitle": (None, None),
        "currentCreator": (None, None),
        "currentCreatorId": (None, None),
        "currentCategory": (None, None),
        "deviceId": (None, None),
        "listeningPattern": ({}, CACHE_SCOPE),
        "playCount": (0, CORE_SCOPE),
        "playHistory": ([], CACHE_SCOPE),
        "followedCreators": ([], None),
        "pendingFollowSource": (None, DIALOG_SCOPE),
        "latitude": (None, CORE_SCOPE),
        "longitude": (None, CORE_SCOPE),
        "localityResolvedAt": (None, CORE_SCOPE),
        "userName": (None, None),
        "userEmail": (None, None),
        "userAddress": (None, None),
        "fullName": (None, None),
        "listenerProfileResolvedAt": (None, CORE_SCOPE),
        "listenerProfileSkipUntil": (None, CORE_SCOPE),
        "browseCatalog": (None, None),
        "currentSummary": (None, None),
        "launchBrowseIds": (None, None),
        "pendingDiscoveryIntent": (None, None),
        "pendingDiscoveryCategory": (None, None),
        "pendingBrowseItems": (None, None),
        "devicePostalCode": (None, CORE_SCOPE),
        "deviceCountryCode": (None, CORE_SCOPE),
        "awaitingContinueAfterFlag": (False, DIALOG_SCOPE),
        "feedbackAskedForToken": (None, None),
        "feedbackAskedTokens": ([], None),
        "feedbackGivenTokens": ([], None),
        "playbackDurationEstimateMs": (None, None),
        "userCity": (None, CORE_SCOPE),
        "userState": (None, None),
        "userCountry": (None, None),
        "currentPlaybackSpeeds": (None, PLAYBACK_SCOPE),
        "playbackQueue": (None, PLAYBACK_SCOPE),
        "preparedNextContent": (None, PLAYBACK_SCOPE),
        "browseQueueItems": (None, None),
        "activePlayback": (None, PLAYBACK_SCOPE),
        "awaitingResume": (False, DIALOG_SCOPE),
        "launchCount": (0, CORE_SCOPE),
        "firstLaunchedAt": (None, CORE_SCOPE),
        "lastLaunchedAt": (None, CORE_SCOPE),
        "listModeActive": (False, DIALOG_SCOPE),
        "listenerId": (None, None),
        "onboardingComplete": (False, CORE_SCOPE),
        "onboardingStage": (None, CORE_SCOPE),
        "onboardingRetries": (0, CORE_SCOPE),
        "onboardingTownAttempts": (0, CORE_SCOPE),
        "onboardingTownResolverFailures": (0, CORE_SCOPE),
        "pendingLocationConfirm": (None, DIALOG_SCOPE),
        "awaitingLocationConfirm": (False, DIALOG_SCOPE),
        "awaitingCommunityPlayback": (False, DIALOG_SCOPE),
        "awaitingProfilePermission": (False, DIALOG_SCOPE),
        "awaitingProfileSetupConsent": (False, DIALOG_SCOPE),
        "awaitingProfileTown": (False, DIALOG_SCOPE),
        "profileSetupActive": (False, DIALOG_SCOPE),
        "listenerType": ("guest", CORE_SCOPE),
        "locationSource": (None, CORE_SCOPE),
        "awaitingSearchConfirmation": (False, DIALOG_SCOPE),
        "pendingResolution": (None, DIALOG_SCOPE),
        "pendingAmbiguity": (None, DIALOG_SCOPE),
        "pendingSuggestions": ([], DIALOG_SCOPE),
        "suggestionIndex": (0, DIALOG_SCOPE),
        "excludedSuggestions": ([], DIALOG_SCOPE),
        "lastCompletedSource": (None, CACHE_SCOPE),
        "pendingLatestSource": (None, DIALOG_SCOPE),
        "lastLatestSourceOfferContentId": (None, CACHE_SCOPE),
        "deferredIntent": (None, None),
    }
    DEFAULT_STORE = {name: specification[0] for name, specification in FIELD_SPECS.items()}
    PERSISTED_FIELDS = frozenset(
        name for name, specification in FIELD_SPECS.items() if specification[1]
    )
    LEGACY_DATABASE_FIELDS = frozenset(
        {
            "feedbackHistory",
            "reportHistory",
            "feedbackCandidates",
            "publicationFeedbackProgress",
            "answeredFeedbackKeys",
            "followedCreators",
        }
    )
    # Historical single-document playback fields are accepted only while
    # hydrating an older record. They are never current persisted fields.
    LEGACY_PLAYBACK_FIELDS = frozenset(
        {
            "lastOffsetMs",
            "currentContentId",
            "currentContentTitle",
            "currentCreator",
            "currentCreatorId",
            "currentCategory",
            "currentAudioUrl",
            "currentDurationSecs",
            "currentPublicationId",
            "feedbackContentTitle",
            "feedbackCreator",
            "feedbackCreatorId",
            "currentTrackIndex",
            "currentTotalTracks",
            "currentTracks",
            "upcomingQueue",
            "queueIndex",
            "queueSource",
            "queueLocality",
            "queueCategory",
            "queueItemsCompleted",
            "playbackParentId",
            "playbackContentType",
            "playbackContentId",
            "activeListenSession",
            "playbackSession",
        }
    )

    @classmethod
    def scope_for(cls, field: str) -> str | None:
        specification = cls.FIELD_SPECS.get(field)
        return specification[1] if specification else None

    @classmethod
    def default_for(cls, field: str):
        specification = cls.FIELD_SPECS.get(field)
        return deepcopy(specification[0]) if specification else None

    @classmethod
    def defaults(cls) -> dict:
        return deepcopy(cls.DEFAULT_STORE)

    @classmethod
    def fields_for_scope(cls, scope: str) -> frozenset[str]:
        return frozenset(
            name for name, specification in cls.FIELD_SPECS.items() if specification[1] == scope
        )
