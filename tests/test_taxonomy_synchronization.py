from __future__ import annotations

import pytest

from config import settings
from src.resolver.taxonomy import TaxonomyManager, TaxonomyRecord, TaxonomySnapshot
from src.resolver.taxonomy.synchronization import (
    TaxonomySyncClient,
    TaxonomySyncUnavailable,
)


class Response:
    def __init__(self, payload: dict, *, status_error: Exception | None = None):
        self._payload = payload
        self._status_error = status_error
        self.content = b"{}"

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return self._payload


def _client(monkeypatch, *, strict: bool) -> tuple[TaxonomySyncClient, object]:
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("7", [
        TaxonomyRecord("category", "sport", entity_id="sport", slug="sport")
    ])
    monkeypatch.setattr(settings, "HEAR_TAXONOMY_RUNTIME_URL", "https://example.test/runtime")
    monkeypatch.setattr(settings, "HEAR_TAXONOMY_STRICT_SYNC", strict)
    client = TaxonomySyncClient(manager)
    return client, manager.snapshot


def test_non_strict_sync_keeps_active_snapshot_when_changes_fail(monkeypatch):
    client, active = _client(monkeypatch, strict=False)
    responses = iter([
        Response({"currentRevision": 8}),
        Response({}, status_error=RuntimeError("changes unavailable")),
    ])
    monkeypatch.setattr(client._client, "get", lambda *_args, **_kwargs: next(responses))

    assert client.ensure_current() is active


def test_strict_sync_rejects_request_when_changes_fail(monkeypatch):
    client, _ = _client(monkeypatch, strict=True)
    responses = iter([
        Response({"currentRevision": 8}),
        Response({}, status_error=RuntimeError("changes unavailable")),
    ])
    monkeypatch.setattr(client._client, "get", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(TaxonomySyncUnavailable) as caught:
        client.ensure_current()

    assert caught.value.required == 8
    assert caught.value.available == 7
