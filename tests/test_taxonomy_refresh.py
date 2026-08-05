from __future__ import annotations

import hashlib
import json

import pytest

from src.resolver.taxonomy import TaxonomyManager


class Response:
    def __init__(self, payload: dict, raw: bytes | None = None):
        self._payload = payload
        self.content = raw or json.dumps(payload, separators=(",", ":")).encode()

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_refresh_rejects_legacy_json_manifest(monkeypatch, tmp_path):
    manifest = {"revision": "old", "artifacts": []}
    monkeypatch.setattr(
        "src.resolver.taxonomy.manager.httpx.get",
        lambda *_args, **_kwargs: Response(manifest),
    )
    manager = TaxonomyManager(cache_dir=tmp_path)
    original = manager.snapshot

    with pytest.raises(ValueError, match="schema-v2 SQLite"):
        manager.refresh("https://example.test/runtime/taxonomy/manifest.json")

    assert manager.snapshot is original


def test_refresh_verifies_immutable_manifest_hash(monkeypatch, tmp_path):
    raw = b'{"schemaVersion":2,"currentRevision":7,"snapshotRevision":7}'
    manifest = json.loads(raw)
    monkeypatch.setattr(
        "src.resolver.taxonomy.manager.httpx.get",
        lambda *_args, **_kwargs: Response(manifest, raw),
    )
    manager = TaxonomyManager(cache_dir=tmp_path)

    with pytest.raises(ValueError, match="manifest hash mismatch"):
        manager.refresh(
            "https://example.test/manifests/manifest-7-deadbeef.json",
            expected_manifest_sha256=hashlib.sha256(b"different").hexdigest(),
        )


def test_offline_loader_rejects_legacy_json_package(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": "legacy", "files": []}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="schema-v2 SQLite"):
        TaxonomyManager().load_directory(tmp_path)
