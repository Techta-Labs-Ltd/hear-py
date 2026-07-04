"""Text preprocessing using spaCy for entity recognition and tokenization."""

from __future__ import annotations

from src.nlp.wink_instance import get_spacy_nlp


def preprocess_utterance(raw: str | None) -> dict:
    """Preprocess a raw user utterance into tokens, stems, entities, and more."""
    if not raw or not str(raw).strip():
        return {
            "raw": "",
            "tokens": [],
            "stems": [],
            "nouns": [],
            "people": [],
            "places": [],
            "organisations": [],
            "customEntities": [],
        }

    text = str(raw).strip()
    nlp = get_spacy_nlp()
    doc = nlp(text)

    tokens = [token.text for token in doc]
    stems = [token.lemma_.lower() for token in doc]
    nouns = [token.text for token in doc if token.pos_ == "NOUN"]

    people: list[str] = []
    places: list[str] = []
    organisations: list[str] = []

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            people.append(ent.text)
        elif ent.label_ in ("GPE", "LOC"):
            places.append(ent.text)
        elif ent.label_ == "ORG":
            organisations.append(ent.text)

    return {
        "raw": text,
        "tokens": tokens,
        "stems": stems,
        "nouns": nouns,
        "people": people,
        "places": places,
        "organisations": organisations,
        "customEntities": [],
    }
