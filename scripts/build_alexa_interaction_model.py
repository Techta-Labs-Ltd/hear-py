from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


class AlexaInteractionModelBuilder:
    SLOT_NAMES = (
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_CREATOR",
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

    @classmethod
    def build(cls, model_path: Path, slot_directory: Path) -> dict:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        types = {
            item["name"]: item
            for item in model["interactionModel"]["languageModel"]["types"]
        }
        missing = [slot_name for slot_name in cls.SLOT_NAMES if slot_name not in types]
        if missing:
            raise ValueError(f"Interaction model is missing slot types: {', '.join(missing)}")
        for slot_name in cls.SLOT_NAMES:
            types[slot_name]["values"] = cls._slot_values(
                slot_directory / f"{slot_name}.csv"
            )
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
        parser.add_argument(
            "--slots", type=Path, default=Path("alexa-slot-imports")
        )
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
