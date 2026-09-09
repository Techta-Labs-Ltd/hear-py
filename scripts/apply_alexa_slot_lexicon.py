from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
from pathlib import Path


class AlexaSlotLexicon:
    DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "config" / "alexa_slot_lexicon.json"
    SLOT_NAMES = (
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_CREATOR",
        "HEAR_TOPIC",
    )
    GENERIC_TOPIC_VALUES = frozenset(
        {"creator", "organization", "organisation", "publication", "talking news", "talking newspaper"}
    )

    @staticmethod
    def _read(path: Path) -> list[list[str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        for index, row in enumerate(rows, start=1):
            if len(row) < 2 or row[1]:
                raise ValueError(f"{path.name} row {index} must have a blank ID column")
        return rows

    @staticmethod
    def _apply_rules(rows: list[list[str]], rules: dict, slot_name: str) -> list[list[str]]:
        removals = {str(value).casefold() for value in rules.get("removeValues", [])}
        rows = [row for row in rows if row[0].casefold() not in removals]
        patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in rules.get("removeSynonymPatterns", [])
        ]
        for row in rows:
            row[2:] = [
                synonym
                for synonym in row[2:]
                if not any(pattern.search(synonym) for pattern in patterns)
            ]
        by_value = {row[0]: row for row in rows}
        for canonical, additions in rules.get("addSynonyms", {}).items():
            row = by_value.get(canonical)
            if row is None:
                raise ValueError(f"{slot_name} is missing canonical value {canonical!r}")
            existing = {synonym.casefold() for synonym in row[2:]}
            for addition in additions:
                if addition.casefold() not in existing:
                    row.append(addition)
                    existing.add(addition.casefold())
        return rows

    @staticmethod
    def _validate(rows: list[list[str]], slot_name: str) -> None:
        canonical_owners: dict[str, str] = {}
        for row in rows:
            canonical = row[0].strip()
            key = canonical.casefold()
            if not canonical or len(canonical) > 140 or key in canonical_owners:
                raise ValueError(f"{slot_name} has an invalid canonical value {canonical!r}")
            canonical_owners[key] = canonical
        synonym_owners: dict[str, str] = {}
        for row in rows:
            owner = row[0]
            owner_key = owner.casefold()
            local: set[str] = set()
            for synonym in row[2:]:
                key = synonym.strip().casefold()
                if not key or len(synonym) > 140 or key in local:
                    raise ValueError(f"{slot_name} has an invalid synonym {synonym!r}")
                if key in canonical_owners and key != owner_key:
                    raise ValueError(
                        f"{slot_name} synonym {synonym!r} collides with "
                        f"{canonical_owners[key]!r}"
                    )
                previous = synonym_owners.get(key)
                if previous and previous != owner:
                    raise ValueError(
                        f"{slot_name} synonym {synonym!r} belongs to multiple values"
                    )
                local.add(key)
                synonym_owners[key] = owner
        if slot_name == "HEAR_TOPIC":
            invalid = sorted(set(canonical_owners).intersection(AlexaSlotLexicon.GENERIC_TOPIC_VALUES))
            if invalid:
                raise ValueError(
                    f"{slot_name} contains generic source kinds: {', '.join(invalid)}"
                )

    @staticmethod
    def _validate_cross_slot(
        slots: dict[str, list[list[str]]], allowed: set[str]
    ) -> None:
        owners: dict[str, set[str]] = {}
        for slot_name, rows in slots.items():
            for row in rows:
                key = row[0].strip().casefold()
                if key:
                    owners.setdefault(key, set()).add(slot_name)
        collisions = {
            phrase: slot_names
            for phrase, slot_names in owners.items()
            if len(slot_names) > 1 and phrase not in allowed
        }
        if collisions:
            examples = "; ".join(
                f"{phrase!r} in {', '.join(sorted(slot_names))}"
                for phrase, slot_names in sorted(collisions.items())[:20]
            )
            raise ValueError(f"Cross-slot phrase collisions found: {examples}")

    @staticmethod
    def _remove_cross_owned_values(
        rows: list[list[str]], reference_rows: list[list[str]]
    ) -> list[list[str]]:
        reference_values = {row[0].strip().casefold() for row in reference_rows}
        return [row for row in rows if row[0].strip().casefold() not in reference_values]

    @staticmethod
    def _write_atomic(path: Path, rows: list[list[str]]) -> None:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
            temporary = Path(handle.name)
        temporary.replace(path)

    @classmethod
    def apply(cls, directory: Path, manifest_path: Path | None = None) -> dict[str, int]:
        manifest = json.loads(
            (manifest_path or cls.DEFAULT_MANIFEST).read_text(encoding="utf-8")
        )
        slots = {
            slot_name: cls._read(directory / f"{slot_name}.csv")
            for slot_name in cls.SLOT_NAMES
        }
        for slot_name in cls.SLOT_NAMES:
            rules = manifest.get(slot_name, {})
            rows = cls._apply_rules(slots[slot_name], rules, slot_name)
            for reference_slot in rules.get("removeCanonicalValuesPresentIn", []):
                if reference_slot not in slots:
                    raise ValueError(f"Unknown reference slot {reference_slot!r}")
                rows = cls._remove_cross_owned_values(rows, slots[reference_slot])
            cls._validate(rows, slot_name)
            slots[slot_name] = rows
        allowed = {
            str(value).strip().casefold()
            for value in manifest.get("allowCrossSlotCollisions", [])
            if str(value).strip()
        }
        cls._validate_cross_slot(slots, allowed)
        for slot_name, rows in slots.items():
            path = directory / f"{slot_name}.csv"
            cls._write_atomic(path, rows)
        return {slot_name: len(rows) for slot_name, rows in slots.items()}


class AlexaSlotLexiconCommand:
    @staticmethod
    def run() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("directory", nargs="?", default="alexa-slot-imports")
        parser.add_argument("--manifest", type=Path, default=AlexaSlotLexicon.DEFAULT_MANIFEST)
        arguments = parser.parse_args()
        for slot_name, count in AlexaSlotLexicon.apply(
            Path(arguments.directory), arguments.manifest
        ).items():
            print(f"{slot_name}: {count} rows")


if __name__ == "__main__":
    AlexaSlotLexiconCommand.run()
