"""Immutable taxonomy snapshots and atomic refresh management."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx
import boto3
from rapidfuzz import fuzz, process

from config import settings
from src.resolver.normalize import CONTENT_NOUNS
from src.resolver.models import (
    AmbiguousCandidate,
    AmbiguousReference,
    ResolvedEntity,
)

logger = logging.getLogger(__name__)
_PHRASE_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.I)


def _phrase_key(value: str) -> str:
    return " ".join(match.group(0).lower() for match in _PHRASE_WORD.finditer(value))

ENTITY_TYPE_ALIASES = {
    "organisation": "organization",
    "organisations": "organization",
    "org": "organization",
    "categories": "category",
    "creators": "creator",
    "publications": "publication",
    "locations": "location",
    "tags": "tag",
}
GENERIC_ALIASES = {
    "a", "all", "about", "and", "around", "by", "for", "from", "give", "hear",
    "i", "in", "me", "my", "near", "on", "play", "please", "put", "search",
    "show", "some", "something", "the", "to", "want",
    "latest", "newest", "news", "content", "creator", "organization",
    "organisation", "publication", "location", "tag", "today", "yesterday",
}
RESERVED_SINGLE_TAXONOMY_TERMS = CONTENT_NOUNS


@dataclass(frozen=True)
class TaxonomyRecord:
    entity_type: str
    canonical: str
    entity_id: str | None = None
    slug: str | None = None
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def _consolidate_equivalent_records(
    records: Iterable[TaxonomyRecord],
) -> tuple[TaxonomyRecord, ...]:
    """Merge duplicate IDs representing the same spoken taxonomy entity."""
    grouped: dict[tuple[str, str], list[TaxonomyRecord]] = {}
    for record in records:
        key = (record.entity_type, record.canonical.strip().casefold())
        grouped.setdefault(key, []).append(record)
    consolidated = []
    for equivalents in grouped.values():
        first = equivalents[0]
        ids = tuple(dict.fromkeys(
            record.entity_id for record in equivalents if record.entity_id
        ))
        metadata = dict(first.metadata)
        if len(ids) > 1:
            metadata["equivalentIds"] = ids
        consolidated.append(TaxonomyRecord(
            entity_type=first.entity_type,
            canonical=first.canonical,
            entity_id=first.entity_id,
            slug=first.slug,
            aliases=tuple(dict.fromkeys(
                alias for record in equivalents for alias in record.aliases
            )),
            metadata=metadata,
        ))
    return tuple(consolidated)


class TaxonomySnapshot:
    def __init__(self, revision: str, records: Iterable[TaxonomyRecord]):
        self.revision = revision
        self.records = _consolidate_equivalent_records(records)
        self.exact_by_phrase: dict[str, list[TaxonomyRecord]] = {}
        self.ambiguous_by_phrase: dict[str, tuple[TaxonomyRecord, ...]] = {}
        self.max_phrase_words = 1
        self.fuzzy: dict[str, dict[str, TaxonomyRecord]] = {}
        alias_owners: dict[tuple[str, str], set[str]] = {}
        alias_records: dict[tuple[str, str], list[TaxonomyRecord]] = {}
        canonical_phrase_owners: dict[tuple[str, str], set[str]] = {}
        for record in self.records:
            identity = record.entity_id or record.slug or record.canonical
            canonical = record.canonical.strip().lower()
            canonical_phrase_owners.setdefault(
                (record.entity_type, canonical.replace("-", " ")), set()
            ).add(identity)
            for alias in (record.canonical, *record.aliases):
                normalized_alias = str(alias or "").strip().lower()
                if normalized_alias:
                    alias_owners.setdefault(
                        (record.entity_type, normalized_alias), set()
                    ).add(identity)
                    alias_records.setdefault(
                        (record.entity_type, normalized_alias), []
                    ).append(record)
        ambiguous_aliases = {
            alias
            for (entity_type, alias), owners in alias_owners.items()
            if entity_type in {"creator", "organization", "publication"}
            and alias not in GENERIC_ALIASES
            and alias not in RESERVED_SINGLE_TAXONOMY_TERMS
            and len(alias) >= 2
            and len(owners) > 1
        }
        for index, alias in enumerate(sorted(ambiguous_aliases)):
            records = []
            seen_names = set()
            for entity_type in ("organization", "publication", "creator"):
                for record in alias_records.get((entity_type, alias), []):
                    name = record.canonical.strip().lower()
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    records.append(record)
            if len(records) < 2:
                continue
            records.sort(key=lambda record: record.canonical.casefold())
            key = _phrase_key(alias)
            self.ambiguous_by_phrase[key] = tuple(records)
            self.max_phrase_words = max(self.max_phrase_words, len(key.split()))
        for index, record in enumerate(self.records):
            canonical = record.canonical.strip().lower()
            identity = record.entity_id or record.slug or record.canonical
            raw_aliases = tuple(dict.fromkeys((
                record.canonical,
                canonical.replace("-", " "),
                *record.aliases,
            )))
            accepted_aliases = []
            for alias in raw_aliases:
                normalized_alias = str(alias or "").strip().lower()
                if len(normalized_alias) < 2:
                    continue
                if (
                    record.entity_type in {"category", "tag"}
                    and normalized_alias in RESERVED_SINGLE_TAXONOMY_TERMS
                ):
                    continue
                canonical_claims = canonical_phrase_owners.get(
                    (record.entity_type, normalized_alias), set()
                )
                if canonical_claims:
                    if len(canonical_claims) != 1 or identity not in canonical_claims:
                        continue
                elif len(alias_owners.get(
                    (record.entity_type, normalized_alias), set()
                )) != 1:
                    continue
                if (
                    normalized_alias in GENERIC_ALIASES
                    and normalized_alias not in {canonical, canonical.replace("-", " ")}
                ):
                    continue
                accepted_aliases.append(normalized_alias)
            aliases = tuple(dict.fromkeys(accepted_aliases))
            if not aliases:
                continue
            choices = self.fuzzy.setdefault(record.entity_type, {})
            for alias in aliases:
                key = _phrase_key(alias)
                self.exact_by_phrase.setdefault(key, []).append(record)
                self.max_phrase_words = max(self.max_phrase_words, len(key.split()))
                choices[alias] = record

    def _phrase_spans(self, text: str):
        words = list(_PHRASE_WORD.finditer(text))
        for start_index, first in enumerate(words):
            limit = min(self.max_phrase_words, len(words) - start_index)
            for word_count in range(1, limit + 1):
                last = words[start_index + word_count - 1]
                yield (
                    " ".join(
                        words[index].group(0).lower()
                        for index in range(start_index, start_index + word_count)
                    ),
                    first.start(),
                    last.end(),
                )

    def exact(self, text: str, excluded: list[tuple[int, int]] | None = None) -> list[ResolvedEntity]:
        excluded = excluded or []
        candidates: list[ResolvedEntity] = []
        for phrase, start, end in self._phrase_spans(text):
            if any(start < stop and end > begin for begin, stop in excluded):
                continue
            for record in self.exact_by_phrase.get(phrase, ()):
                candidates.append(ResolvedEntity(
                    record.entity_type, record.entity_id,
                    record.slug or record.canonical, text[start:end], 1.0, "exact",
                    start, end, record.metadata,
                ))
        type_priority = {
            "organization": 0, "publication": 1, "creator": 2,
            "location": 3, "category": 4, "tag": 5,
        }
        candidates.sort(key=lambda item: (
            -(item.end - item.start), item.start,
            type_priority.get(item.entity_type, 99),
        ))
        accepted: list[ResolvedEntity] = []
        for item in candidates:
            if not any(item.start < other.end and item.end > other.start for other in accepted):
                accepted.append(item)
        return sorted(accepted, key=lambda item: item.start)

    def ambiguous(
        self,
        text: str,
        excluded: list[tuple[int, int]] | None = None,
    ) -> list[AmbiguousReference]:
        excluded = excluded or []
        matches = []
        for phrase, start, end in self._phrase_spans(text):
            if any(start < stop and end > begin for begin, stop in excluded):
                continue
            records = self.ambiguous_by_phrase.get(phrase)
            if not records:
                continue
            matches.append(AmbiguousReference(
                phrase=text[start:end],
                candidates=tuple(
                    AmbiguousCandidate(
                        entity_type=record.entity_type,
                        entity_id=record.entity_id,
                        canonical_value=record.slug or record.canonical,
                    )
                    for record in records
                ),
                start=start,
                end=end,
            ))
        matches.sort(key=lambda item: (-(item.end - item.start), item.start))
        accepted = []
        for item in matches:
            if not any(item.start < other.end and item.end > other.start for other in accepted):
                accepted.append(item)
        return sorted(accepted, key=lambda item: item.start)

    def fuzzy_match(
        self,
        phrase: str,
        entity_type: str,
        *,
        minimum_score: int | None = None,
    ) -> ResolvedEntity | None:
        choices = self.fuzzy.get(entity_type, {})
        if not choices or len(phrase.strip()) < 4:
            return None
        results = process.extract(
            phrase.lower(),
            choices.keys(),
            scorer=fuzz.ratio,
            limit=min(len(choices), 20),
        )
        if not results:
            return None
        by_identity: dict[str, tuple[str, float, TaxonomyRecord]] = {}
        for alias, score, _ in results:
            record = choices[alias]
            identity = record.entity_id or record.slug or record.canonical
            current = by_identity.get(identity)
            if current is None or score > current[1]:
                by_identity[identity] = (alias, score, record)
        ranked = sorted(by_identity.values(), key=lambda item: item[1], reverse=True)
        alias, score, record = ranked[0]
        # Context-scoped proper names may use the plan's supported 0.85-0.91
        # range; unscoped fuzzy matching is never attempted.
        threshold = minimum_score if minimum_score is not None else 88
        if score < threshold:
            return None
        if len(ranked) > 1 and score - ranked[1][1] < 3:
            return None
        return ResolvedEntity(
            record.entity_type, record.entity_id, record.slug or record.canonical,
            phrase, score / 100.0, "fuzzy", 0, len(phrase), record.metadata,
        )


def _records_from_payload(entity_type: str, payload: Any) -> list[TaxonomyRecord]:
    entity_type = ENTITY_TYPE_ALIASES.get(entity_type, entity_type)
    items = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        canonical = item.get("canonical") or item.get("name") or item.get("city") or item.get("slug")
        if not canonical:
            continue
        aliases = (
            item.get("aliases") or item.get("phrases") or item.get("synonyms") or []
        )
        if entity_type == "category":
            canonical = item.get("id") or item.get("canonical") or canonical
        records.append(TaxonomyRecord(
            entity_type=entity_type,
            canonical=str(canonical),
            entity_id=str(item.get("id")) if item.get("id") else None,
            slug=str(item.get("slug")) if item.get("slug") else None,
            aliases=tuple(str(value) for value in aliases if value),
            metadata={
                **(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
                **{key: item[key] for key in ("city", "countryCode", "country_code", "lat", "lng")
                   if item.get(key) is not None},
            },
        ))
    return records


def bundled_location_records(root: Path | None = None) -> list[TaxonomyRecord]:
    """Load the only package-owned taxonomy: stable location data."""
    records: list[TaxonomyRecord] = []
    location_path = (root or Path(__file__).parents[1]) / "data" / "locations.json"
    try:
        locations = json.loads(location_path.read_text(encoding="utf-8"))
        records.extend(_records_from_payload("location", locations))
    except (OSError, json.JSONDecodeError):
        logger.warning("Bundled location taxonomy could not be loaded")
    return records


def _records_from_alias_payload(payload: Any) -> list[TaxonomyRecord]:
    """Convert the manifest's alias-to-entity index into taxonomy records."""
    if not isinstance(payload, dict):
        return []
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for alias, owner in payload.items():
        if not alias or not isinstance(owner, dict):
            continue
        entity_type = ENTITY_TYPE_ALIASES.get(
            str(owner.get("entity_type") or owner.get("type") or "").lower(),
            str(owner.get("entity_type") or owner.get("type") or "").lower(),
        )
        if entity_type not in {"creator", "organization", "publication"}:
            continue
        entity_id = str(owner.get("id") or owner.get("entity_id") or "")
        canonical = str(owner.get("name") or owner.get("canonical") or "").strip()
        if not entity_id or not canonical:
            continue
        item = grouped.setdefault(
            (entity_type, entity_id),
            {"canonical": canonical, "aliases": [], "metadata": {}},
        )
        item["aliases"].append(str(alias))
    return [
        TaxonomyRecord(
            entity_type=entity_type,
            canonical=item["canonical"],
            entity_id=entity_id,
            aliases=tuple(dict.fromkeys(item["aliases"])),
            metadata=item["metadata"],
        )
        for (entity_type, entity_id), item in grouped.items()
    ]


class TaxonomyManager:
    """Own the active immutable snapshot and atomically replace valid revisions."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        bundle_dir: Path | None = None,
    ):
        self._lock = threading.RLock()
        self._snapshot = TaxonomySnapshot("bundled-locations", bundled_location_records())
        self._forced_revision: str | None = None
        self._last_revision_check = 0.0
        self._refresh_lock = threading.Lock()
        self.cache_dir = cache_dir or Path(
            os.environ.get("HEAR_TAXONOMY_CACHE_DIR", "/tmp/hear-taxonomy")
        )
        configured_bundle = bundle_dir or (
            Path(settings.HEAR_TAXONOMY_BUNDLE_DIR)
            if settings.HEAR_TAXONOMY_BUNDLE_DIR
            else None
        )
        if configured_bundle and (configured_bundle / "manifest.json").is_file():
            try:
                self.load_directory(configured_bundle)
            except (OSError, ValueError, json.JSONDecodeError):
                logger.exception(
                    "Bundled taxonomy snapshot is invalid; using locations only"
                )
        runtime_bucket = settings.HEAR_TAXONOMY_SNAPSHOT_BUCKET
        runtime_key = settings.HEAR_TAXONOMY_SNAPSHOT_KEY
        if runtime_bucket and runtime_key:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                archive = self.cache_dir / "snapshot.tar.gz"
                boto3.client("s3").download_file(runtime_bucket, runtime_key, str(archive))
                with tarfile.open(archive, "r:gz") as source:
                    members = source.getmembers()
                    if any(Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members):
                        raise ValueError("Unsafe taxonomy archive")
                    source.extractall(self.cache_dir)
                self.load_directory(self.cache_dir)
                expected = settings.HEAR_TAXONOMY_ACTIVE_REVISION
                if expected and self.snapshot.revision != expected:
                    raise ValueError("Runtime taxonomy revision mismatch")
            except Exception:
                logger.exception("Runtime taxonomy snapshot could not be loaded")

    @property
    def snapshot(self) -> TaxonomySnapshot:
        with self._lock:
            return self._snapshot

    def mark_stale(self, revision: str) -> None:
        self._forced_revision = revision
        self._last_revision_check = 0.0

    def refresh_if_needed(self) -> bool:
        """Check the shared revision at a bounded interval and refresh if stale."""
        now = time.monotonic()
        interval = max(settings.HEAR_TAXONOMY_REFRESH_SECONDS, 1)
        if not self._forced_revision and now - self._last_revision_check < interval:
            return False
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            self._last_revision_check = now
            manifest_url = settings.HEAR_TAXONOMY_MANIFEST_URL
            expected_revision = self._forced_revision
            if settings.HEAR_TAXONOMY_REVISION_TABLE:
                try:
                    table = boto3.resource(
                        "dynamodb", region_name=settings.ddb_region,
                    ).Table(settings.HEAR_TAXONOMY_REVISION_TABLE)
                    item = table.get_item(
                        Key={"pk": "taxonomy#current"},
                        ConsistentRead=False,
                    ).get("Item") or {}
                    expected_revision = str(
                        item.get("revision") or expected_revision or ""
                    )
                    manifest_url = str(item.get("manifestUrl") or manifest_url)
                except Exception:
                    logger.warning(
                        "Taxonomy revision lookup failed; using configured manifest",
                        exc_info=True,
                    )
            if expected_revision and expected_revision == self.snapshot.revision:
                self._forced_revision = None
                return False
            return self.refresh(manifest_url)
        finally:
            self._refresh_lock.release()

    def refresh(self, manifest_url: str | None = None) -> bool:
        url = manifest_url or settings.HEAR_TAXONOMY_MANIFEST_URL
        if not url:
            return False
        response = httpx.get(url, timeout=httpx.Timeout(8.0, connect=2.0))
        response.raise_for_status()
        manifest = response.json()
        revision = str(
            manifest.get("revision") or manifest.get("generatedAt") or manifest.get("version") or ""
        )
        if not revision or (revision == self.snapshot.revision and revision != self._forced_revision):
            return False
        records = bundled_location_records()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        files = manifest.get("files") or []
        for descriptor in files:
            if not isinstance(descriptor, dict):
                continue
            file_url = descriptor.get("url") or urljoin(
                url, descriptor.get("path") or descriptor.get("name") or ""
            )
            filename = Path(str(file_url)).name
            is_alias_index = Path(filename).stem.lower() == "aliases"
            entity_type = str(
                descriptor.get("entityType") or descriptor.get("type") or Path(filename).stem
            ).lower()
            entity_type = ENTITY_TYPE_ALIASES.get(entity_type, entity_type.rstrip("s"))
            if not is_alias_index and entity_type not in {
                "category", "creator", "organization", "publication", "tag"
            }:
                continue
            expected_hash = descriptor.get("sha256") or descriptor.get("hash")
            cache_path = self.cache_dir / filename
            content = cache_path.read_bytes() if cache_path.exists() else b""
            digest = hashlib.sha256(content).hexdigest() if content else ""
            expected = str(expected_hash or "").removeprefix("sha256:")
            if not content or (expected and not digest.startswith(expected)):
                file_response = httpx.get(
                    file_url, timeout=httpx.Timeout(12.0, connect=3.0),
                )
                file_response.raise_for_status()
                content = file_response.content
                digest = hashlib.sha256(content).hexdigest()
            if expected and not digest.startswith(expected):
                raise ValueError(f"Taxonomy hash mismatch for {file_url}")
            cache_path.write_bytes(content)
            payload = json.loads(content)
            records.extend(
                _records_from_alias_payload(payload)
                if is_alias_index
                else _records_from_payload(entity_type, payload)
            )
        candidate = TaxonomySnapshot(revision, records)
        if not candidate.records:
            raise ValueError("Taxonomy candidate is empty")
        temporary_manifest = self.cache_dir / "manifest.json.tmp"
        temporary_manifest.write_text(
            json.dumps(manifest, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_manifest.replace(self.cache_dir / "manifest.json")
        with self._lock:
            self._snapshot = candidate
            self._forced_revision = None
        return True

    def load_directory(self, directory: Path) -> bool:
        """Load a downloaded production snapshot without making network calls."""
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        records = bundled_location_records()
        for descriptor in manifest.get("files") or []:
            filename = str(descriptor.get("name") or descriptor.get("path") or "")
            is_alias_index = Path(filename).stem.lower() == "aliases"
            entity_type = ENTITY_TYPE_ALIASES.get(Path(filename).stem.lower(), Path(filename).stem.rstrip("s"))
            if not is_alias_index and entity_type not in {
                "category", "creator", "organization", "publication", "tag"
            }:
                continue
            content = (directory / filename).read_bytes()
            expected = str(descriptor.get("sha256") or descriptor.get("hash") or "").removeprefix("sha256:")
            if expected and not hashlib.sha256(content).hexdigest().startswith(expected):
                raise ValueError(f"Taxonomy hash mismatch for {filename}")
            payload = json.loads(content)
            records.extend(
                _records_from_alias_payload(payload)
                if is_alias_index
                else _records_from_payload(entity_type, payload)
            )
        revision = str(
            manifest.get("revision") or manifest.get("generatedAt") or manifest.get("version") or "offline"
        )
        candidate = TaxonomySnapshot(revision, records)
        with self._lock:
            self._snapshot = candidate
            self._forced_revision = None
        return True


taxonomy_manager = TaxonomyManager()
