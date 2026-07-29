import json

import pytest

from src.services.taxonomy_updates import handle_taxonomy_webhook


@pytest.mark.asyncio
async def test_taxonomy_webhook_marks_revision_stale(monkeypatch):
    observed = {}
    monkeypatch.setattr("src.services.taxonomy_updates._store_revision", lambda revision, url: observed.update(
        revision=revision, url=url,
    ))
    monkeypatch.setattr("src.services.taxonomy_updates.taxonomy_manager.mark_stale",
                        lambda revision: observed.update(stale=revision))
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
        "stale": "revision-3",
    }
