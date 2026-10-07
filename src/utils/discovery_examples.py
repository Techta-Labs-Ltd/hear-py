"""Recovery examples drawn from the canonical names in the shipped Alexa model."""

import json
import random
from functools import lru_cache
from html import escape
from pathlib import Path


class DiscoveryExamples:
    DEFAULT_NEWSPAPER = "York Talking News"

    @staticmethod
    @lru_cache(maxsize=1)
    def newspaper_names() -> tuple[str, ...]:
        try:
            model = json.loads(
                (Path(__file__).resolve().parents[2] / "en-GB.json").read_text(encoding="utf-8")
            )
            types = model["interactionModel"]["languageModel"]["types"]
            names = tuple(
                dict.fromkeys(
                    entry["name"]["value"].strip()
                    for slot_type in types
                    if slot_type.get("name") == "HEAR_ORGANIZATION"
                    for entry in slot_type.get("values", [])
                    if str(entry.get("name", {}).get("value", ""))
                    .casefold()
                    .endswith(("talking news", "talking newspaper"))
                )
            )
            return names or (DiscoveryExamples.DEFAULT_NEWSPAPER,)
        except (OSError, ValueError, KeyError, TypeError):
            return (DiscoveryExamples.DEFAULT_NEWSPAPER,)

    @staticmethod
    def guidance(newspaper: str | None = None) -> str:
        name = escape(newspaper or random.choice(DiscoveryExamples.newspaper_names()), quote=False)
        return f"You can say play {name}, or say the name of your city to begin listening."

    @staticmethod
    def recovery(*, quite: bool = False) -> dict[str, str]:
        guidance = DiscoveryExamples.guidance()
        prefix = "Sorry, I didn't quite catch that." if quite else "Sorry, I didn't catch that."
        return {"speech": f"{prefix} {guidance}", "reprompt": guidance}
