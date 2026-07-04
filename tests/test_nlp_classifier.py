import pytest
from src.nlp.classifier import classify_utterance
from src.nlp.patterns import (
    TRENDING_HINTS, LOCAL_HINTS, FEEDBACK_ENJOYED_HINTS,
    FEEDBACK_NOT_ENJOYED_HINTS, FEEDBACK_SKIP_HINTS,
)


class TestClassifier:
    def test_feedback_enjoyed_intent(self):
        result = classify_utterance("that was great")
        assert result["intent"] == "feedback_enjoyed"
        assert result["confidence"] == "high"

    def test_feedback_not_enjoyed_intent(self):
        result = classify_utterance("not good")
        assert result["intent"] == "feedback_not_enjoyed"
        assert result["confidence"] == "high"

    def test_feedback_skip_intent(self):
        result = classify_utterance("skip")
        assert result["intent"] == "feedback_skip"
        assert result["confidence"] == "high"

    def test_trending_intent(self):
        result = classify_utterance("what's trending")
        assert result["intent"] == "trending"

    def test_local_intent(self):
        result = classify_utterance("what's local")
        assert result["intent"] == "local"

    def test_empty_input_returns_general(self):
        result = classify_utterance("")
        assert result["intent"] == "general"
        assert result["confidence"] == "low"
        assert result["slots"] == {}

    def test_general_topic_search(self):
        result = classify_utterance("play me the latest technology news")
        assert result["intent"] in ("general", "category")
        assert result["slots"].get("latest") is True

    def test_category_detection_sports(self):
        result = classify_utterance("play me something on sports")
        assert result["intent"] in ("category", "general")
