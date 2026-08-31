from __future__ import annotations

import re


class ContentUtils:
    @staticmethod
    def repair_mojibake(value):
        text = ContentUtils.nullable_string(value)
        if not text or not any((marker in text for marker in ("â€", "â€™", "Ã", "Â"))):
            return text
        try:
            return text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text

    @staticmethod
    def nullable_string(value):
        if value is None:
            return None
        s = str(value).strip()
        return s or None

    @staticmethod
    def is_id_like_label(value) -> bool:
        if not isinstance(value, str):
            return True
        t = value.strip()
        if not t:
            return True
        encoded_identifier = any(
            (
                re.fullmatch("[a-z]?\\d+(?:[-_]\\d+)*", t, re.I),
                re.search("\\d{3,}[_-]post", t, re.I),
                re.search("[_-]post\\d+", t, re.I),
                re.search("track\\d+", t, re.I) and re.search("post|_", t),
            )
        )
        if encoded_identifier:
            return True
        if re.search("\\s", t):
            return False
        if len(t) <= 12:
            return False
        return bool(
            re.search("[_/\\\\\\.:]", t)
            or re.search("\\d{4,}", t)
            or (len(t) > 16 and re.match("^[a-z0-9-]+$", t, re.I) and re.search("\\d", t))
        )

    @staticmethod
    def is_weak_title(value) -> bool:
        """Check whether a title is weak/generic and should not be spoken."""
        if not isinstance(value, str):
            return True
        t = value.strip()
        if not t:
            return True
        if re.match("^test\\s*\\d*$", t, re.I):
            return True
        if re.match("^test\\s+\\d+$", t, re.I):
            return True
        if re.match("^untitled$", t, re.I):
            return True
        if re.match("^recording\\s*\\d*$", t, re.I):
            return True
        if ContentUtils._is_breadcrumb_title(t):
            return True
        return False

    @staticmethod
    def _is_breadcrumb_title(value: str) -> bool:
        """Check whether a title is a breadcrumb path (contains >)."""
        if not isinstance(value, str):
            return False
        return ">" in value.strip()

    @staticmethod
    def prefer_readable(*candidates) -> str | None:
        """Pick the most human-readable candidate from a series of values."""
        first_any = None
        first_non_id = None
        for candidate in candidates:
            s = ContentUtils.nullable_string(candidate)
            if not s:
                continue
            if first_any is None:
                first_any = s
            if not ContentUtils.is_id_like_label(s) and (not ContentUtils.is_weak_title(s)):
                return s
            if first_non_id is None and (not ContentUtils.is_id_like_label(s)):
                first_non_id = s
        return first_non_id or first_any

    @staticmethod
    def _first_search_phrase(item: dict) -> str | None:
        """Get the first search phrase from a content item."""
        phrases = item.get("searchPhrases")
        if not isinstance(phrases, list):
            return None
        for p in phrases:
            s = ContentUtils.nullable_string(p)
            if s:
                return s
        return None

    @staticmethod
    def _themes_label(item: dict) -> str | None:
        """Build a label from theme tags."""
        themes = item.get("themes")
        if not isinstance(themes, list) or not themes:
            return None
        parts = [ContentUtils.nullable_string(t) for t in themes[:2]]
        parts = [p for p in parts if p]
        return ", ".join(parts) if parts else None

    @staticmethod
    def _pick_curated_title(item: dict) -> str | None:
        return ContentUtils.prefer_readable(
            ContentUtils.nullable_string(item.get("shortDescription")),
            ContentUtils._first_search_phrase(item),
            ContentUtils._themes_label(item),
        )

    @staticmethod
    def _pick_display_title(item: dict) -> str:
        actual = ContentUtils.prefer_readable(
            item.get("displayTitle"), item.get("spokenTitle"), item.get("title")
        )
        if (
            actual
            and (not ContentUtils.is_weak_title(actual))
            and (not ContentUtils.is_id_like_label(actual))
        ):
            return actual
        curated = ContentUtils._pick_curated_title(item)
        if (
            curated
            and (not ContentUtils.is_weak_title(curated))
            and (not ContentUtils.is_id_like_label(curated))
        ):
            return curated
        return actual or curated or "a local recording"

    @staticmethod
    def pick_spoken_title(item: dict) -> str:
        return ContentUtils._pick_display_title(item)

    @staticmethod
    def is_bad_credit_name(value) -> bool:
        """Check whether a credit name is unusable for spoken output."""
        if not value:
            return True
        raw = str(value).strip()
        if not raw or ContentUtils.is_id_like_label(raw):
            return True
        t = raw.lower()
        words = [w for w in raw.split() if w]
        return bool(
            re.match("^(super\\s+)?admin(istrator)?$", t)
            or t in {"unknown", "system", "admin"}
            or len(raw) > 48
            or len(words) > 5
            or (len(words) >= 5 and raw == t)
            or re.match("^(really|so|scared)(?:\\s+|$)", raw, re.I)
            or re.search("\\b(the force|right help|coming from|so happy to be)\\b", t)
            or (
                len(words) >= 3
                and raw == t
                and re.search("\\b(from|coming|happy|force|help|right)\\b", t)
            )
        )

    @staticmethod
    def _is_independent_org(name) -> bool:
        n = str(name or "").strip().lower()
        return n in ("independent", "independent creator")

    @staticmethod
    def _is_bad_organization_name(value) -> bool:
        raw = str(value or "").strip()
        if not raw or len(raw) > 120 or ContentUtils.is_id_like_label(raw):
            return True
        return raw.lower() in {"unknown", "system", "admin", "administrator"}

    @staticmethod
    def _extract_creator_name(item: dict) -> str | None:
        creator = item.get("creator")
        if isinstance(creator, dict):
            return ContentUtils.repair_mojibake(creator.get("name"))
        return ContentUtils.repair_mojibake(creator) or ContentUtils.repair_mojibake(
            item.get("creatorName")
        )

    @staticmethod
    def _extract_creator_id(item: dict) -> str | None:
        creator = item.get("creator")
        if isinstance(creator, dict):
            return creator.get("id") or None
        return item.get("creatorId") or None

    @staticmethod
    def _pick_organization_name(item: dict) -> str | None:
        org = item.get("organization")
        if isinstance(org, dict):
            name = ContentUtils.repair_mojibake(org.get("name"))
            if name:
                return name
        return ContentUtils.repair_mojibake(item.get("organizationName"))

    @staticmethod
    def _is_organization_publisher(item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        org = ContentUtils._pick_organization_name(item)
        return bool(
            org
            and (not ContentUtils._is_independent_org(org))
            and (not ContentUtils._is_bad_organization_name(org))
        )

    @staticmethod
    def pick_attribution_credit(item: dict) -> str | None:
        creator = ContentUtils._extract_creator_name(item)
        org = ContentUtils._pick_organization_name(item)
        org_pub = ContentUtils._is_organization_publisher(item)
        if org_pub and org:
            return org
        if creator and (not ContentUtils.is_bad_credit_name(creator)):
            return creator
        if (
            org
            and (not ContentUtils._is_bad_organization_name(org))
            and (not ContentUtils._is_independent_org(org))
        ):
            return org
        return None

    @staticmethod
    def pick_content_credit(item: dict) -> str | None:
        """Pick the content credit for playback attribution."""
        return ContentUtils.pick_attribution_credit(item)

    @staticmethod
    def pick_content_source(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        organization_name = ContentUtils._pick_organization_name(item)
        organization_id = item.get("organizationId")
        organization = item.get("organization")
        if isinstance(organization, dict):
            organization_id = organization.get("id") or organization_id
        if ContentUtils._is_organization_publisher(item) and organization_id:
            return {
                "kind": "organization",
                "id": organization_id,
                "name": organization_name,
            }
        creator_name = ContentUtils._extract_creator_name(item)
        creator_id = ContentUtils._extract_creator_id(item)
        if creator_id and creator_name and (not ContentUtils.is_bad_credit_name(creator_name)):
            return {"kind": "creator", "id": creator_id, "name": creator_name}
        return None

    @staticmethod
    def pick_summary(item: dict) -> str | None:
        return ContentUtils.nullable_string(item.get("shortDescription"))

    @staticmethod
    def content_title_for_speech(item: dict) -> str | None:
        if not isinstance(item, dict):
            return None
        title = (
            item.get("spokenTitle")
            or item.get("displayTitle")
            or ContentUtils.nullable_string(item.get("title"))
        )
        if (
            title
            and (not ContentUtils.is_id_like_label(title))
            and (not ContentUtils.is_weak_title(title))
        ):
            return ContentUtils._humanize_spoken_title_safe(title) or title
        curated = ContentUtils._pick_curated_title(item)
        if (
            curated
            and (not ContentUtils.is_weak_title(curated))
            and (not ContentUtils.is_id_like_label(curated))
        ):
            return ContentUtils._humanize_spoken_title_safe(curated) or curated
        return curated or "a local recording"

    @staticmethod
    def _humanize_spoken_title_safe(value: str) -> str | None:
        """Safely clean a title for speech output."""
        if not isinstance(value, str):
            return None
        t = value.strip()
        if not t or ContentUtils.is_id_like_label(t):
            return None
        return t


class ContentIdentity:
    @staticmethod
    def publication_id(item: dict | None) -> str | None:
        value = item.get("publicationId") if isinstance(item, dict) else None
        return ContentUtils.nullable_string(value)

    @staticmethod
    def content_id(item: dict | None) -> str | None:
        if not isinstance(item, dict):
            return None
        return ContentUtils.nullable_string(
            item.get("contentId") or item.get("trackContentId") or item.get("id")
        )

    @staticmethod
    def is_publication(item: dict | None) -> bool:
        return bool(ContentIdentity.publication_id(item))

    @staticmethod
    def subject_type(item: dict | None) -> str:
        return "publication" if ContentIdentity.is_publication(item) else "content"

    @staticmethod
    def subject_id(item: dict | None) -> str | None:
        return ContentIdentity.publication_id(item) or ContentIdentity.content_id(item)

    @staticmethod
    def subject_key(item: dict | None) -> str | None:
        subject_id = ContentIdentity.subject_id(item)
        if not subject_id:
            return None
        return (
            f"publication:{subject_id}"
            if ContentIdentity.is_publication(item)
            else subject_id
        )

    @staticmethod
    def subject_title(item: dict | None) -> str | None:
        if not isinstance(item, dict):
            return None
        if ContentIdentity.is_publication(item):
            return ContentUtils.nullable_string(item.get("publicationTitle")) or "that publication"
        return ContentUtils.nullable_string(
            item.get("title") or item.get("spokenTitle") or item.get("displayTitle")
        )
