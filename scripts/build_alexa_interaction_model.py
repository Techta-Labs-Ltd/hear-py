from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


class AlexaInteractionModelBuilder:
    SLOT_NAMES = (
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_TOPIC",
    )
    DISCOVERY_SLOT_NAME = "HEAR_DISCOVERY"
    DISCOVERY_ALIAS_SLOT_NAMES = (
        "HEAR_ORGANIZATION",
        "HEAR_TOPIC",
    )
    MAX_MODEL_BYTES = 1_500_000

    @staticmethod
    def _slot_values(path: Path) -> list[dict]:
        values: list[dict] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.reader(handle), start=1):
                if len(row) < 2 or not row[0].strip() or row[1].strip():
                    raise ValueError(f"{path.name} row {row_number} is invalid")
                name: dict[str, object] = {"value": row[0].strip()}
                synonyms = [value.strip() for value in row[2:] if value.strip()]
                if synonyms:
                    name["synonyms"] = synonyms
                values.append({"name": name})
        return values

    @staticmethod
    def _merge_seed_synonyms(values: list[dict], seed_values: list[dict]) -> list[dict]:
        seed_by_canonical = {
            str(item["name"]["value"]).casefold(): item["name"].get("synonyms", [])
            for item in seed_values
        }
        canonical_keys = {str(item["name"]["value"]).casefold() for item in values}
        phrase_owners: dict[str, set[str]] = {}
        for item in values:
            canonical_key = str(item["name"]["value"]).casefold()
            phrases = [item["name"]["value"], *item["name"].get("synonyms", [])]
            for phrase in phrases:
                phrase_owners.setdefault(str(phrase).casefold(), set()).add(canonical_key)
        for canonical_key, synonyms in seed_by_canonical.items():
            if canonical_key not in canonical_keys:
                continue
            for synonym in synonyms:
                phrase_owners.setdefault(str(synonym).casefold(), set()).add(canonical_key)
        for item in values:
            name = item["name"]
            canonical_key = str(name["value"]).casefold()
            synonyms = list(name.get("synonyms", []))
            seen = {str(value).casefold() for value in synonyms}
            for synonym in seed_by_canonical.get(canonical_key, []):
                synonym_key = str(synonym).casefold()
                if (
                    synonym_key == canonical_key
                    or synonym_key in seen
                    or phrase_owners.get(synonym_key) != {canonical_key}
                ):
                    continue
                seen.add(synonym_key)
                synonyms.append(synonym)
            if synonyms:
                name["synonyms"] = synonyms
        return values

    @classmethod
    def build(cls, model_path: Path, slot_directory: Path) -> dict:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        types = {item["name"]: item for item in model["interactionModel"]["languageModel"]["types"]}
        missing = [slot_name for slot_name in cls.SLOT_NAMES if slot_name not in types]
        if cls.DISCOVERY_SLOT_NAME not in types:
            missing.append(cls.DISCOVERY_SLOT_NAME)
        if missing:
            raise ValueError(f"Interaction model is missing slot types: {', '.join(missing)}")
        slot_values: dict[str, list[dict]] = {}
        for slot_name in cls.SLOT_NAMES:
            values = cls._merge_seed_synonyms(
                cls._slot_values(slot_directory / f"{slot_name}.csv"),
                types[slot_name].get("values", []),
            )
            types[slot_name]["values"] = values
            slot_values[slot_name] = values

        phrase_owners: dict[str, set[str]] = {}
        for values in slot_values.values():
            for item in values:
                canonical = str(item["name"]["value"])
                canonical_key = canonical.casefold()
                phrases = [canonical, *item["name"].get("synonyms", [])]
                for phrase in phrases:
                    phrase_owners.setdefault(str(phrase).casefold(), set()).add(canonical_key)

        discovery_by_canonical: dict[str, dict] = {}
        discovery_synonyms: dict[str, set[str]] = {}
        for slot_name in cls.SLOT_NAMES:
            for item in slot_values[slot_name]:
                canonical = str(item["name"]["value"])
                canonical_key = canonical.casefold()
                discovery = discovery_by_canonical.setdefault(
                    canonical_key, {"name": {"value": canonical}}
                )
                if slot_name not in cls.DISCOVERY_ALIAS_SLOT_NAMES:
                    continue
                seen = discovery_synonyms.setdefault(canonical_key, set())
                synonyms = discovery["name"].setdefault("synonyms", [])
                for synonym in item["name"].get("synonyms", []):
                    synonym = str(synonym)
                    synonym_key = synonym.casefold()
                    if (
                        synonym_key == canonical_key
                        or synonym_key in seen
                        or phrase_owners.get(synonym_key) != {canonical_key}
                    ):
                        continue
                    seen.add(synonym_key)
                    synonyms.append(synonym)
                if not synonyms:
                    discovery["name"].pop("synonyms", None)
        discovery_values = list(discovery_by_canonical.values())
        types[cls.DISCOVERY_SLOT_NAME]["values"] = discovery_values
        return model

    @classmethod
    def serialize(cls, model: dict) -> str:
        payload = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
        size = len(payload.encode("utf-8"))
        if size > cls.MAX_MODEL_BYTES:
            raise ValueError(
                f"Alexa interaction model is {size} bytes; limit is {cls.MAX_MODEL_BYTES}"
            )
        return payload

    @classmethod
    def write(cls, model_path: Path, slot_directory: Path, output_path: Path) -> None:
        payload = cls.serialize(cls.build(model_path, slot_directory))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")


class AlexaInteractionModelCommand:
    @staticmethod
    def run() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--model", type=Path, default=Path("en-GB.json"))
        parser.add_argument("--slots", type=Path, default=Path("alexa-slot-imports"))
        parser.add_argument("--output", type=Path, required=True)
        arguments = parser.parse_args()
        AlexaInteractionModelBuilder.write(
            arguments.model,
            arguments.slots,
            arguments.output,
        )
        print(f"Wrote Alexa interaction model to {arguments.output}")


if __name__ == "__main__":
    AlexaInteractionModelCommand.run()
