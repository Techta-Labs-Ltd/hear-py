import hashlib
import json
from unittest.mock import MagicMock

import pytest

from src.webhooks import taxonomy_seed


def test_bootstrap_queues_numeric_manifest_revision(monkeypatch):
    content = json.dumps({
        "schemaVersion": 2,
        "currentRevision": 9,
        "snapshotRevision": 9,
        "routing": {"exact": {}},
        "shards": {"location": {}},
    }, separators=(",", ":")).encode()
    response = MagicMock()
    response.read.return_value = content
    response.__enter__.return_value = response
    queued = MagicMock()
    monkeypatch.setattr(taxonomy_seed.urllib.request, "urlopen", lambda *args, **kwargs: response)
    monkeypatch.setattr(taxonomy_seed, "queue_taxonomy_snapshot", queued)

    revision = taxonomy_seed.bootstrap_manifest(
        "https://cdn.hear.media/runtime/taxonomy/manifest.json"
    )

    assert revision == 9
    queued.assert_called_once_with(
        9,
        "https://cdn.hear.media/runtime/taxonomy/manifest.json",
        hashlib.sha256(content).hexdigest(),
    )


def test_bootstrap_rejects_incomplete_manifest(monkeypatch):
    response = MagicMock()
    response.read.return_value = json.dumps({
        "schemaVersion": 2,
        "currentRevision": 9,
        "snapshotRevision": 8,
        "routing": {},
        "shards": {},
    }).encode()
    response.__enter__.return_value = response
    monkeypatch.setattr(taxonomy_seed.urllib.request, "urlopen", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="complete schema-v2"):
        taxonomy_seed.bootstrap_manifest("https://example.test/manifest.json")
