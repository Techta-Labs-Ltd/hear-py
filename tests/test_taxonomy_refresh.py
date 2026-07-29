from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.resolver.engine import Resolver
from src.resolver.taxonomy import TaxonomyManager


class Response:
    def __init__(self, payload):
        self.content = json.dumps(payload).encode()
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_refresh_hash_checks_and_atomically_swaps(monkeypatch, tmp_path):
    creators = [{"id": "creator-1", "name": "David Beard", "aliases": ["David"]}]
    digest = hashlib.sha256(json.dumps(creators).encode()).hexdigest()
    manifest = {
        "revision": "revision-2",
        "files": [{
            "entityType": "creator",
            "url": "https://example.test/creators.json",
            "sha256": digest,
        }],
    }

    def fake_get(url, timeout):
        return Response(manifest if url.endswith("manifest.json") else creators)

    monkeypatch.setattr("src.resolver.taxonomy.httpx.get", fake_get)
    manager = TaxonomyManager(cache_dir=tmp_path)
    original = manager.snapshot
    assert manager.refresh("https://example.test/manifest.json")
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    assert manager.snapshot is not original
    assert manager.snapshot.revision == "revision-2"
    matches = manager.snapshot.exact("play from david")
    assert any(item.entity_id == "creator-1" for item in matches)


def test_bad_refresh_keeps_working_snapshot(monkeypatch, tmp_path):
    manifest = {
        "revision": "broken",
        "files": [{
            "entityType": "creator",
            "url": "https://example.test/creators.json",
            "sha256": "wrong",
        }],
    }

    def fake_get(url, timeout):
        return Response(manifest if url.endswith("manifest.json") else [{"name": "David"}])

    monkeypatch.setattr("src.resolver.taxonomy.httpx.get", fake_get)
    manager = TaxonomyManager(cache_dir=tmp_path)
    original = manager.snapshot
    try:
        manager.refresh("https://example.test/manifest.json")
    except ValueError:
        pass
    assert manager.snapshot is original


def test_manifest_alias_index_routes_creator_and_organization(tmp_path):
    aliases = {
        "dave": {
            "id": "creator-1",
            "name": "David Beard",
            "entity_type": "creator",
        },
        "residents group": {
            "id": "org-1",
            "name": "Havering Residents Association",
            "entity_type": "org",
        },
    }
    creators = [{"id": "creator-1", "name": "David Beard"}]
    organizations = [{
        "id": "org-1",
        "name": "Havering Residents Association",
    }]
    files = {
        "aliases.json": aliases,
        "creators.json": creators,
        "organisations.json": organizations,
    }
    manifest = {"version": "alias-test", "files": []}
    for name, payload in files.items():
        content = json.dumps(payload).encode()
        (tmp_path / name).write_bytes(content)
        manifest["files"].append({
            "name": name,
            "hash": hashlib.sha256(content).hexdigest(),
        })
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    manager = TaxonomyManager()
    assert manager.load_directory(tmp_path)
    matches = manager.snapshot.exact("play news from dave and residents group")
    assert {(item.entity_type, item.entity_id) for item in matches} == {
        ("creator", "creator-1"),
        ("organization", "org-1"),
    }


def test_org_alias_from_manifest_uses_canonical_organization_type(tmp_path):
    aliases = {
        "tnf": {
            "id": "org-tnf",
            "name": "Talking News Federation",
            "entity_type": "org",
        },
    }
    content = json.dumps(aliases).encode()
    (tmp_path / "aliases.json").write_bytes(content)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "version": "org-alias-test",
        "files": [{
            "name": "aliases.json",
            "hash": hashlib.sha256(content).hexdigest(),
        }],
    }), encoding="utf-8")

    manager = TaxonomyManager()
    assert manager.load_directory(tmp_path)
    plan = Resolver(manager).resolve("play me something from tnf")

    assert plan.organization_ids == ["org-tnf"]
    assert plan.query == ""


def test_downloaded_production_snapshot_loads_offline():
    fixture = Path(__file__).parent / "fixtures" / "taxonomy"
    manager = TaxonomyManager()
    assert manager.load_directory(fixture)
    assert manager.snapshot.revision == "2026-07-28T03:00:09.736973+00:00"
    matches = manager.snapshot.exact("play accessibility")
    assert any(item.entity_type == "category" and item.canonical_value == "accessibility"
               for item in matches)


def test_manager_bootstraps_an_offline_bundle():
    fixture = Path(__file__).parent / "fixtures" / "taxonomy"
    manager = TaxonomyManager(bundle_dir=fixture)

    plan = Resolver(manager).resolve(
        "play the latest sound recording in burnley"
    )

    assert manager.snapshot.revision == "2026-07-28T03:00:09.736973+00:00"
    assert plan.category_slugs == ["sound-recording"]
    assert plan.city == "Burnley"
