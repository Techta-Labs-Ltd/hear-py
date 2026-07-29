from __future__ import annotations

import json
from pathlib import Path

from src.resolver.engine import Resolver
from src.resolver.taxonomy import TaxonomyManager


def test_one_hundred_golden_alexa_utterances():
    dataset = json.loads(
        (Path(__file__).parent / "golden_utterances.json").read_text(encoding="utf-8")
    )
    manager = TaxonomyManager()
    manager.load_directory(Path(__file__).parent / "fixtures" / "taxonomy")
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
