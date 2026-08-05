"""Production-schema resolver tests using a validated SQLite snapshot package."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.resolver.search import Resolver
from src.resolver.taxonomy import TaxonomyManager


@pytest.fixture(scope="module")
def sqlite_resolver() -> Resolver:
    package = Path(os.environ.get("HEAR_TEST_TAXONOMY_DIR", ""))
    if not package.is_dir() or not (package / "manifest.json").is_file():
        pytest.skip("HEAR_TEST_TAXONOMY_DIR does not contain a schema-v2 package")
    manager = TaxonomyManager(cache_dir=package)
    manager.load_directory(package)
    return Resolver(manager)


def test_sqlite_snapshot_resolves_every_entity_path(sqlite_resolver: Resolver):
    category_and_location = sqlite_resolver.resolve(
        "play the latest sport in london"
    )
    assert category_and_location.category_slugs == ["sport"]
    assert category_and_location.city == "London"
    assert category_and_location.country_code == "gb"
    assert category_and_location.sort == "latest"
    assert category_and_location.ambiguous_references == []

    organization = sqlite_resolver.resolve("play from york talking news")
    assert organization.organization_ids == [
        "63915f39-db54-4001-9877-7d2b3fc36639"
    ]
    assert organization.category_slugs == []
    assert organization.tags == []

    creator = sqlite_resolver.resolve("play news from adeshina")
    assert creator.category_slugs == ["news"]
    assert set(creator.creator_ids) == {
        "ec8267de-6331-42de-a14d-4a44a221a93c",
        "4cd2cb60-1314-4f66-841d-e49ed4820a3b",
    }
    assert creator.ambiguous_references == []

    location = sqlite_resolver.resolve("i live in burnley")
    assert location.city == "Burnley"
    assert location.query == ""


def test_sqlite_snapshot_preserves_real_ambiguity(sqlite_resolver: Resolver):
    plan = sqlite_resolver.resolve("play wtn")
    assert plan.organization_ids == []
    assert len(plan.ambiguous_references) == 1
    candidates = plan.ambiguous_references[0].candidates
    assert len(candidates) > 2
    assert {candidate.entity_type for candidate in candidates} == {"organization"}
    assert any(candidate.canonical_value == "Walsall Talking Newspaper" for candidate in candidates)
