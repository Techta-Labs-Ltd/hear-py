from __future__ import annotations

import argparse
import json
from pathlib import Path


class AlexaInteractionModelBuilder:
    """Validate and serialize the checked-in Alexa interaction model.

    Custom HEAR slot types remain in the model, but their values are curated in
    en-GB.json.  Backend catalogues must not be copied into the Alexa model.
    """

    RETAINED_SLOT_NAMES = (
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_TOPIC",
    )
    DISCOVERY_SLOT_NAME = "HEAR_DISCOVERY"
    MAX_MODEL_BYTES = 1_500_000

    @classmethod
    def build(cls, model_path: Path, invocation_name: str | None = None) -> dict:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        if invocation_name is not None:
            normalized_invocation = invocation_name.strip()
            if not normalized_invocation:
                raise ValueError("Alexa invocation name cannot be empty")
            model["interactionModel"]["languageModel"]["invocationName"] = (
                normalized_invocation
            )
        types = {
            item["name"]
            for item in model["interactionModel"]["languageModel"]["types"]
        }
        required = (*cls.RETAINED_SLOT_NAMES, cls.DISCOVERY_SLOT_NAME)
        missing = [slot_name for slot_name in required if slot_name not in types]
        if missing:
            raise ValueError(
                f"Interaction model is missing slot types: {', '.join(missing)}"
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
    def write(
        cls,
        model_path: Path,
        output_path: Path,
        invocation_name: str | None = None,
    ) -> None:
        payload = cls.serialize(cls.build(model_path, invocation_name))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")


class AlexaInteractionModelCommand:
    @staticmethod
    def run() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--model", type=Path, default=Path("en-GB.json"))
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--invocation-name")
        arguments = parser.parse_args()
        AlexaInteractionModelBuilder.write(
            arguments.model,
            arguments.output,
            arguments.invocation_name,
        )
        print(f"Wrote Alexa interaction model to {arguments.output}")


if __name__ == "__main__":
    AlexaInteractionModelCommand.run()
