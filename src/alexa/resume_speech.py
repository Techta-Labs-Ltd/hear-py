from __future__ import annotations

from src.alexa.speech import Speech


class ResumeSpeech:
    CREATOR_SOURCES = frozenset({"creator", "playbycreatorintent"})
    ORGANIZATION_SOURCES = frozenset({"organization", "playbyorganizationintent"})
    PUBLICATION_SOURCES = frozenset({"publication", "playpublicationintent"})
    PLACEHOLDER_LABELS = frozenset(
        {
            "a publication",
            "a recording",
            "independent creator",
            "that creator",
            "that organization",
            "that publication",
            "that recording",
            "that source",
            "unknown",
            "untitled",
        }
    )

    @staticmethod
    def _safe_label(value, *, credit: bool = False) -> str | None:
        label = Speech.humanize_spoken_title(value)
        if (
            not label
            or label.casefold() in ResumeSpeech.PLACEHOLDER_LABELS
            or (credit and Speech.is_bad_credit(label))
        ):
            return None
        return Speech.escape_ssml_lite(label)

    @staticmethod
    def _source(active: dict, store: dict) -> str:
        queue = store.get("playbackQueue") or {}
        source = active.get("discoverySource") or queue.get("source") or ""
        return str(source).strip().lower()

    @staticmethod
    def _question(statement: str | None = None) -> str:
        if not statement:
            statement = "You were listening to a recording"
        punctuation = "" if statement.endswith((".", "!", "?")) else "."
        return f"{statement}{punctuation} Would you like to continue?"

    @classmethod
    def prompt(cls, subject: dict | None, store: dict | None = None) -> str:
        active = subject if isinstance(subject, dict) else {}
        saved = store if isinstance(store, dict) else {}
        source = cls._source(active, saved)

        is_publication = bool(
            source in cls.PUBLICATION_SOURCES
            or active.get("publicationId")
            or active.get("subjectType") == "publication"
        )
        if is_publication:
            publication = cls._safe_label(
                active.get("publicationTitle") or active.get("subjectTitle")
            )
            publisher = cls._safe_label(active.get("organizationName"), credit=True)
            publisher = publisher or cls._safe_label(active.get("creatorName"), credit=True)
            if publication and publisher and publication.casefold() != publisher.casefold():
                return cls._question(
                    f"You were listening to {publication}, from {publisher}"
                )
            if publication:
                return cls._question(f"You were listening to {publication}")
            if publisher:
                return cls._question(
                    f"You were listening to a publication from {publisher}"
                )
            return cls._question("You were listening to a publication")

        if source in cls.ORGANIZATION_SOURCES or source == "latest_source":
            organization = cls._safe_label(active.get("organizationName"), credit=True)
            if organization:
                return cls._question(f"You were listening to {organization}")
            creator = cls._safe_label(active.get("creatorName"), credit=True)
            if creator:
                return cls._question(f"You were listening to {creator}")

        if source in cls.CREATOR_SOURCES or source == "latest_source":
            creator = cls._safe_label(active.get("creatorName"), credit=True)
            if creator:
                return cls._question(f"You were listening to {creator}")

        description = cls._safe_label(
            active.get("summary") or active.get("spokenTitle") or active.get("title")
        )
        return cls._question(
            f"You were listening to {description}" if description else None
        )

    @classmethod
    def reprompt(cls, subject: dict | None, store: dict | None = None) -> str:
        return f"{cls.prompt(subject, store)} Please say yes or no."
