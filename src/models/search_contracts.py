from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str = ""
    intent: str = "general"
    filters: dict[str, Any] = field(default_factory=dict)
    page: int = 0
    limit: int | None = None
    max_pages: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", str(self.query or ""))
        object.__setattr__(self, "intent", str(self.intent or "general"))
        object.__setattr__(self, "filters", deepcopy(dict(self.filters or {})))
        object.__setattr__(self, "page", max(0, int(self.page or 0)))
        if self.limit is not None:
            object.__setattr__(self, "limit", max(1, int(self.limit)))
        if self.max_pages is not None:
            object.__setattr__(self, "max_pages", max(1, int(self.max_pages)))



@dataclass(frozen=True, slots=True)
class SearchOutcome:
    kind: Literal["success", "empty", "ambiguous", "invalid", "unavailable"]
    results: tuple[dict[str, Any], ...] = ()
    total_hits: int = 0
    page: int = 0
    total_pages: int = 0
    message: str | None = None

    @classmethod
    def classify(cls, response: dict | None) -> "SearchOutcome":
        payload = response if isinstance(response, dict) else {}
        results = tuple(item for item in payload.get("results") or () if isinstance(item, dict))
        try:
            total_hits = max(0, int(payload.get("total_hits") or 0))
        except (TypeError, ValueError):
            total_hits = 0
        try:
            page = max(0, int(payload.get("page") or 0))
        except (TypeError, ValueError):
            page = 0
        try:
            total_pages = max(0, int(payload.get("total_pages") or 0))
        except (TypeError, ValueError):
            total_pages = 0
        message = str(payload.get("client_message") or "").strip() or None
        if payload.get("failed"):
            kind: Literal["success", "empty", "ambiguous", "invalid", "unavailable"] = "unavailable"
        elif payload.get("invalid"):
            kind = "invalid"
        elif payload.get("ambiguous") or payload.get("_publication_choices"):
            kind = "ambiguous"
        elif results:
            kind = "success"
        else:
            kind = "empty"
        return cls(kind, tuple(deepcopy(item) for item in results), total_hits, page, total_pages, message)

    @property
    def is_success(self) -> bool:
        return self.kind == "success"

class CatalogueSearchGateway(Protocol):
    async def search(
        self,
        payload: dict | None = None,
        timeout_ms: int | None = None,
    ) -> dict:
        ...
