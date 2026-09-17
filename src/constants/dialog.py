from src.constants.state import StateSchema


class DialogConstants:
    VALIDATION_FAILURE = "_dialogValidationFailure"
    DIALOG_TTL_SECONDS = 10 * 60
    CHOICE_DISMISS_INTENTS = frozenset({"DismissChoicesIntent"})
    IDLE_AFFIRMATIVE_PHRASES = frozenset(
        {
            "yes",
            "yeah",
            "yep",
            "sure",
            "ok",
            "okay",
            "yes please",
            "aye",
            "correct",
            "right",
            "alright",
            "all right",
        }
    )
    CHOICE_DISMISS_PHRASES = frozenset(
        {
            "something else",
            "none of these",
            "none of those",
            "neither",
            "neither of these",
            "neither of those",
            "no",
            "nope",
            "none",
            "nothing",
            "another thing",
            "another thing else",
            "different",
            "something different",
            "go back",
            "return to search",
            "go back to search",
            "back to search",
            "i dont want any of these",
            "i don't want any of these",
            "none of them",
            "not any of these",
            "cancel",
        }
    )
    DIALOG_LEGACY_FLAGS = StateSchema.DIALOG_LEGACY_FLAGS
    SLOT_CAPTURE = {
        "creator_location": {
            "intentName": "SelectCreatorCityIntent",
            "slotName": "cityQuery",
        },
        "organization_name": {
            "intentName": "SelectOrganizationIntent",
            "slotName": "organizationQuery",
        },
        "publication_source": {
            "intentName": "SelectPublicationSourceIntent",
            "slotName": "publicationSourceQuery",
        },
    }
    TRANSIENT_DISCOVERY_DIALOGS = frozenset(
        {
            "search_confirmation",
            "ambiguity",
            "availability",
            "asr_repair",
            "organization_name",
            "creator_location",
            "publication_source",
            "help",
        }
    )
    DEFERRED_DISCOVERY_INTENTS = frozenset(
        {
            "OpenDiscoveryIntent",
            "PlayContentIntent",
            "PlayLocalIntent",
            "PlayRecommendationIntent",
            "PlayByOrganizationIntent",
            "SelectOrganizationIntent",
            "SelectCreatorCityIntent",
            "SelectPublicationSourceIntent",
            "PlayPublicationIntent",
            "BrowseContentIntent",
            "WhatsTrendingIntent",
        }
    )
