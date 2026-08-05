from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.resolver.search import Resolver
from src.resolver.taxonomy import TaxonomyManager


def test_one_hundred_golden_alexa_utterances():
    dataset = json.loads(
        (Path(__file__).parent / "golden_utterances.json").read_text(encoding="utf-8")
    )
    manager = TaxonomyManager()
    package = Path(os.environ.get("HEAR_TEST_TAXONOMY_DIR", ""))
    if not package.is_dir() or not (package / "manifest.json").is_file():
        pytest.skip("HEAR_TEST_TAXONOMY_DIR does not contain a schema-v2 package")
    manager.load_directory(package)
    resolver = Resolver(manager)
    cases = [
        (template.format(category=category["spoken"]), category["slug"])
        for template in dataset["templates"]
        for category in dataset["categories"]
    ]
    assert len(cases) >= 100
    for utterance, expected_slug in cases:
        plan = resolver.resolve(utterance)
        assert plan.category_slugs == [expected_slug], utterance
        assert plan.query == "", utterance
