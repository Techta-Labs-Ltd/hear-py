import json

import pytest

from src.services.taxonomy_updates import handle_taxonomy_webhook


@pytest.mark.asyncio
async def test_taxonomy_webhook_records_revision_without_loading_resolver(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        "src.services.taxonomy_updates.queue_taxonomy_snapshot",
        lambda revision, url, digest: observed.update(
            revision=revision, url=url, digest=digest,
        ),
    )
    digest = "a" * 64
    result = await handle_taxonomy_webhook({"body": json.dumps({
        "event": "taxonomy.snapshot.published",
        "schemaVersion": 1,
        "revision": 3,
        "manifestUrl": "https://example.test/manifests/manifest-3-aaaa.json",
        "manifestSha256": digest,
    })})
    assert result["statusCode"] == 202
    assert observed == {
        "revision": 3,
        "url": "https://example.test/manifests/manifest-3-aaaa.json",
        "digest": digest,
    }
