from __future__ import annotations

import hashlib
import json
import threading

import httpx

from config import settings
from .manager import TaxonomyManager, taxonomy_manager


class TaxonomySyncUnavailable(RuntimeError):
    def __init__(self, required: int, available: int, reason: str):
        super().__init__(reason)
        self.required = required
        self.available = available


class TaxonomySyncClient:
    def __init__(self, manager: TaxonomyManager | None = None):
        self.manager = manager or taxonomy_manager
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(0.5, connect=0.3),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"Accept": "application/json"},
        )

    @staticmethod
    def _revision(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def ensure_current(self, requested_revision: int = 0):
        active = self.manager.snapshot
        available = self._revision(active.revision)
        base_url = settings.HEAR_TAXONOMY_RUNTIME_URL.rstrip("/")
        if not base_url:
            if requested_revision > available and settings.HEAR_TAXONOMY_STRICT_SYNC:
                raise TaxonomySyncUnavailable(requested_revision, available, "runtime URL is not configured")
            return active
        try:
            response = self._client.get(
                f"{base_url}/revision",
                headers={"X-Api-Key": settings.api_key} if settings.api_key else None,
            )
            response.raise_for_status()
            revision_document = response.json()
            authoritative = self._revision(revision_document.get("currentRevision"))
        except Exception as exc:
            if settings.HEAR_TAXONOMY_STRICT_SYNC:
                raise TaxonomySyncUnavailable(requested_revision or available, available, "revision lookup failed") from exc
            return active
        target = max(requested_revision, authoritative)
        if target <= available:
            return active
        with self._lock:
            active = self.manager.snapshot
            available = self._revision(active.revision)
            if target <= available:
                return active
            maximum = max(int(settings.HEAR_TAXONOMY_MAX_INLINE_CHANGES), 1)
            if target - available > maximum:
                if settings.HEAR_TAXONOMY_STRICT_SYNC:
                    raise TaxonomySyncUnavailable(
                        target, available, "taxonomy range exceeds inline limit"
                    )
                return active
            try:
                response = self._client.get(
                    f"{base_url}/changes",
                    params={"after": available, "to": target},
                    headers={"X-Api-Key": settings.api_key} if settings.api_key else None,
                )
                response.raise_for_status()
                if len(response.content) > 5 * 1024 * 1024:
                    raise ValueError("taxonomy response exceeds size limit")
                payload = response.json()
                changes = payload.get("changes")
                if (
                    int(payload.get("schemaVersion") or 0) != 1
                    or int(payload.get("fromRevision") or -1) != available
                    or int(payload.get("toRevision") or -1) != target
                    or not isinstance(changes, list)
                    or int(payload.get("changeCount") or -1) != len(changes)
                ):
                    raise ValueError("invalid taxonomy range contract")
                canonical = json.dumps(
                    changes,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                expected = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
                if payload.get("checksum") != expected:
                    raise ValueError("taxonomy range checksum mismatch")
                return self.manager.apply_changes(target, changes)
            except TaxonomySyncUnavailable:
                raise
            except Exception as exc:
                if settings.HEAR_TAXONOMY_STRICT_SYNC:
                    raise TaxonomySyncUnavailable(
                        target, available, "taxonomy change sync failed"
                    ) from exc
                return active


taxonomy_sync_client = TaxonomySyncClient()
