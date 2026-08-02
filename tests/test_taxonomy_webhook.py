import json

import pytest

from src.services.taxonomy_updates import handle_taxonomy_webhook


@pytest.mark.asyncio
async def test_taxonomy_webhook_records_revision_without_loading_resolver(monkeypatch):
    observed = {}
    monkeypatch.setattr("src.services.taxonomy_updates._store_revision", lambda revision, url: observed.update(
        revision=revision, url=url,
    ))
    monkeypatch.setattr("src.services.taxonomy_updates._enqueue_refresh", lambda revision, url: observed.update(
        queued_revision=revision, queued_url=url,
    ))
    result = await handle_taxonomy_webhook({"body": json.dumps({
        "event": "taxonomy.updated",
        "schemaVersion": 3,
        "revision": "revision-3",
        "manifestUrl": "https://example.test/manifest.json",
    })})
    assert result["statusCode"] == 202
    assert observed == {
        "revision": "revision-3",
        "url": "https://example.test/manifest.json",
        "queued_revision": "revision-3",
        "queued_url": "https://example.test/manifest.json",
    }
