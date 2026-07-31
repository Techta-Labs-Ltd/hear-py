from __future__ import annotations

import json
from pathlib import Path


def test_constrained_latest_utterances_preserve_the_full_topic_slot():
    model = json.loads(
        (Path(__file__).parents[1] / "en-GB.json").read_text(encoding="utf-8")
    )
    intents = {
        item["name"]: item
        for item in model["interactionModel"]["languageModel"]["intents"]
    }
    trending = intents["WhatsTrendingIntent"]

    assert trending["slots"] == [{
        "name": "topic",
        "type": "AMAZON.SearchQuery",
    }]
    assert "what's the latest {topic}" in trending["samples"]
    assert "what is the latest {topic}" in trending["samples"]
