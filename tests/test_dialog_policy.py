from src.models.dialog_policy import DialogPolicy


def test_normalize_removes_punctuation_and_normalizes_ampersands():
    assert DialogPolicy.normalize("  Smith & O'Neil! ") == "smith and oneil"


def test_normalize_ordinal_understands_spoken_selection_phrases():
    assert DialogPolicy.normalize_ordinal("please choose option 2nd") == "second"


def test_dismiss_phrase_is_a_pure_policy_decision():
    assert DialogPolicy.is_dismiss_phrase("none of these") is True
    assert DialogPolicy.is_dismiss_phrase("second") is False
