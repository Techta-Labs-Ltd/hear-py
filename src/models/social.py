from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.utils.content import ContentUtils


@dataclass(frozen=True, slots=True)
class FollowCommand:
    """The canonical source selected for a follow-state transition."""

    source_id: str
    source_name: str
    source_type: Literal["creator", "organization"] = "creator"

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_name.strip():
            raise ValueError("follow command requires a source id and name")
        if self.source_type not in {"creator", "organization"}:
            raise ValueError("follow command requires a supported source type")

    def event_source(self) -> dict:
        return {
            "id": self.source_id,
            "name": self.source_name,
            "type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class FollowReceipt:
    command: FollowCommand
    followed: bool


class FollowingManager:
    __slots__ = ()

    @staticmethod
    def add(followed_items: object, command: FollowCommand) -> tuple[list[dict], FollowReceipt]:
        raw_items = followed_items if isinstance(followed_items, (list, tuple)) else ()
        followed = [dict(item) for item in raw_items if isinstance(item, dict)]
        if any(
            (
                c.get("id") == command.source_id
                and c.get("type", "creator") == command.source_type
                for c in followed
            )
        ):
            return followed, FollowReceipt(command=command, followed=True)
        followed.append(command.event_source())
        return followed, FollowReceipt(command=command, followed=True)

    @staticmethod
    def remove(followed_items: object, command: FollowCommand) -> tuple[list[dict], FollowReceipt]:
        raw_items = followed_items if isinstance(followed_items, (list, tuple)) else ()
        followed = [
            c
            for c in raw_items
            if isinstance(c, dict)
            if not (
                c.get("id") == command.source_id
                and c.get("type", "creator") == command.source_type
            )
        ]
        return followed, FollowReceipt(command=command, followed=False)

    @staticmethod
    def is_following(store: dict, source_id: str, source_type: str = "creator") -> bool:
        return any(
            (
                c.get("id") == source_id and c.get("type", "creator") == source_type
                for c in store.get("followedCreators") or []
            )
        )


class ListeningTracker:
    __slots__ = ()

    @staticmethod
    def _normalize_creator(store: dict, creator) -> str | None:
        if not creator:
            return None
        raw = str(creator).strip()
        if not raw:
            return None
        if not ContentUtils.is_bad_credit_name(raw) and (not ContentUtils.is_id_like_label(raw)):
            return raw
        creator_id = store.get("feedbackCreatorId") or store.get("currentCreatorId") or None
        if creator_id and str(creator_id) == raw:
            name = store.get("feedbackCreator") or store.get("currentCreator") or None
            if (
                name
                and (not ContentUtils.is_bad_credit_name(name))
                and (not ContentUtils.is_id_like_label(name))
            ):
                return str(name).strip()
        for followed in store.get("followedCreators") or []:
            if followed.get("id") == raw:
                name = followed.get("name")
                if name and (not ContentUtils.is_bad_credit_name(name)):
                    return str(name).strip()
        return None

    @staticmethod
    def record(
        store: dict,
        *,
        category: str | None = None,
        creator: str | None = None,
        liked: bool | None = None,
    ) -> dict:
        pattern = dict(store.get("listeningPattern") or {})
        score = 2 if liked is True else -1 if liked is False else 1
        if category:
            key = f"category:{category}"
            pattern[key] = (pattern.get(key) or 0) + score
        creator_label = ListeningTracker._normalize_creator(store, creator)
        if creator_label:
            key = f"creator:{creator_label}"
            pattern[key] = (pattern.get(key) or 0) + score
        return pattern


class Social:
    @staticmethod
    def _follow_source(store: dict) -> dict | None:
        pending = store.get("pendingFollowSource")
        if isinstance(pending, dict) and pending.get("id") and pending.get("name"):
            return pending
        playback = store.get("activePlayback") or {}
        source = ContentUtils.pick_content_source(
            {
                "organizationId": playback.get("organizationId")
                or store.get("currentOrganizationId"),
                "organizationName": playback.get("organizationName")
                or store.get("currentOrganization"),
                "creatorId": playback.get("creatorId")
                or store.get("currentCreatorId")
                or store.get("feedbackCreatorId"),
                "creatorName": playback.get("creatorName")
                or store.get("currentCreator")
                or store.get("feedbackCreator"),
            }
        )
        return source
