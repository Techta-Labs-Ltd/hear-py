from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
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
import zstandard

from config import settings
from src.resolver.normalization import CONTENT_NOUNS
from src.resolver.models import (
    AmbiguousCandidate,
    AmbiguousReference,
    ResolvedEntity,
)
from .sqlite import SQLiteTaxonomySnapshot

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


def _manifest_artifacts(manifest: dict) -> list[tuple[tuple[str, ...], dict]]:
    """Return every schema-v2 artifact descriptor from the manifest tree."""
    artifacts: list[tuple[tuple[str, ...], dict]] = []

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict) and {
            "url", "sha256", "compressedBytes", "uncompressedBytes"
        }.issubset(value):
            artifacts.append((path, value))
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, (*path, str(key)))

    walk(manifest.get("routing") or {}, ("routing",))
    walk(manifest.get("shards") or {}, ("shards",))
    logical = [path for path, _ in artifacts]
    if len(logical) != len(set(logical)):
        raise ValueError("Duplicate taxonomy artifact logical path")
    return artifacts


def _validate_sqlite_artifact(path: Path, logical: tuple[str, ...]) -> None:
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"SQLite quick_check failed for {'.'.join(logical)}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        required = (
            {"route_entities", "route_aliases"}
            if logical == ("routing", "exact")
            else {"entities", "aliases", "alias_fts_core"}
            if logical == ("routing", "core")
            else {"fuzzy_entities", "fuzzy_aliases", "fuzzy_prefix_fts", "fuzzy_trigram_fts"}
            if logical[:2] == ("routing", "fuzzy")
            else {"entities", "aliases"}
            if logical and logical[0] == "shards"
            else set()
        )
        missing = required - tables
        if missing:
            raise ValueError(
                f"SQLite schema missing {sorted(missing)} for {'.'.join(logical)}"
            )
    finally:
        connection.close()


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

    def facet_aliases(self, phrase: str, limit: int = 30):
        ranked = []
        for entity_type in ("category", "tag"):
            choices = self.fuzzy.get(entity_type, {})
            for alias, score, _ in process.extract(
                phrase.lower(), choices.keys(), scorer=fuzz.WRatio,
                limit=min(limit, len(choices)),
            ):
                ranked.append((score, entity_type, alias, choices[alias]))
        ranked.sort(reverse=True, key=lambda item: item[0])
        return tuple(
            (entity_type, alias, record)
            for _, entity_type, alias, record in ranked[:limit]
        )

    def fuzzy_alias_items(self, entity_type: str):
        return tuple(self.fuzzy.get(entity_type, {}).items())


class TaxonomyManager:
    """Own the active immutable snapshot and atomically replace valid revisions."""

    def __init__(
        self,
        cache_dir: Path | None = None,
    ):
        self._lock = threading.RLock()
        self._snapshot = TaxonomySnapshot("0", ())
        self._forced_revision: str | None = None
        self._last_revision_check = 0.0
        self._refresh_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self.cache_dir = cache_dir or Path(
            os.environ.get("HEAR_TAXONOMY_CACHE_DIR", "/tmp/hear-taxonomy")
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

    def apply_changes(self, target_revision: int, changes: list[dict]):
        """Apply one validated contiguous range as an atomic complete-record overlay."""
        with self._sync_lock:
            active = self.snapshot
            current_revision = int(active.revision) if str(active.revision).isdigit() else 0
            if target_revision <= current_revision:
                return active
            expected = list(range(current_revision + 1, target_revision + 1))
            actual = [int(change.get("revision") or 0) for change in changes]
            if actual != expected:
                raise ValueError("Taxonomy change range is not contiguous")
            if isinstance(active, CompositeTaxonomySnapshot):
                base = active.base
                overlay_records = dict(active.overlay_records)
                deleted = set(active.deleted)
            else:
                base = active
                overlay_records = {}
                deleted = set()
            for change in changes:
                entity_type = ENTITY_TYPE_ALIASES.get(
                    str(change.get("entityType") or "").lower(),
                    str(change.get("entityType") or "").lower(),
                )
                entity_id = str(change.get("entityId") or "").strip()
                operation = str(change.get("operation") or "").lower()
                if entity_type not in {
                    "category", "tag", "creator", "organization", "publication", "location"
                } or not entity_id or operation not in {"upsert", "delete"}:
                    raise ValueError("Invalid taxonomy change")
                key = (entity_type, entity_id)
                if operation == "delete":
                    overlay_records.pop(key, None)
                    deleted.add(key)
                    continue
                canonical = str(change.get("canonical") or "").strip()
                aliases = change.get("aliases")
                metadata = change.get("metadata")
                if not canonical or not isinstance(aliases, list) or not isinstance(metadata, dict):
                    raise ValueError("Taxonomy upsert is not a complete entity representation")
                slug = metadata.get("categorySlug") or metadata.get("slug")
                overlay_records[key] = TaxonomyRecord(
                    entity_type=entity_type,
                    canonical=canonical,
                    entity_id=entity_id,
                    slug=str(slug) if slug else None,
                    aliases=tuple(str(alias) for alias in aliases if str(alias).strip()),
                    metadata=dict(metadata),
                )
                deleted.discard(key)
            candidate = CompositeTaxonomySnapshot(
                base,
                target_revision,
                overlay_records,
                deleted,
            )
            with self._lock:
                self._snapshot = candidate
            return candidate

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

    def refresh(
        self,
        manifest_url: str | None = None,
        *,
        expected_manifest_sha256: str | None = None,
    ) -> bool:
        url = manifest_url or settings.HEAR_TAXONOMY_MANIFEST_URL
        if not url:
            return False
        response = httpx.get(url, timeout=httpx.Timeout(8.0, connect=2.0))
        response.raise_for_status()
        if expected_manifest_sha256:
            actual_manifest_sha256 = hashlib.sha256(response.content).hexdigest()
            if actual_manifest_sha256 != expected_manifest_sha256:
                raise ValueError("Taxonomy manifest hash mismatch")
        manifest = response.json()
        if int(manifest.get("schemaVersion") or 0) != 2:
            raise ValueError("Only schema-v2 SQLite taxonomy manifests are supported")
        return self._refresh_sqlite_manifest(url, manifest)

    def _refresh_sqlite_manifest(self, manifest_url: str, manifest: dict) -> bool:
        current_revision = int(manifest.get("currentRevision") or 0)
        snapshot_revision = int(manifest.get("snapshotRevision") or 0)
        if current_revision <= 0 or snapshot_revision != current_revision:
            raise ValueError("Schema-v2 manifest must describe one complete current snapshot")
        if str(current_revision) == self.snapshot.revision and str(current_revision) != self._forced_revision:
            return False
        artifacts = _manifest_artifacts(manifest)
        if not artifacts:
            raise ValueError("Schema-v2 manifest has no artifacts")
        logical_paths = {logical for logical, _ in artifacts}
        for required in (("routing", "core"), ("routing", "exact")):
            if required not in logical_paths:
                raise ValueError(f"Missing required taxonomy artifact: {'.'.join(required)}")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        sqlite_paths: dict[tuple[str, ...], Path] = {}
        seen_filenames: set[str] = set()
        for logical, descriptor in artifacts:
            artifact_url = urljoin(manifest_url, str(descriptor["url"]))
            if not artifact_url.lower().startswith("https://"):
                raise ValueError("Taxonomy artifacts must use HTTPS")
            filename = Path(artifact_url).name
            if not filename or filename in seen_filenames:
                raise ValueError(f"Duplicate taxonomy artifact filename: {filename}")
            seen_filenames.add(filename)
            expected_hash = str(descriptor["sha256"]).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise ValueError(f"Invalid taxonomy hash for {artifact_url}")
            compressed_size = int(descriptor["compressedBytes"])
            uncompressed_size = int(descriptor["uncompressedBytes"])
            if compressed_size <= 0 or uncompressed_size <= 0:
                raise ValueError(f"Invalid taxonomy sizes for {artifact_url}")
            compressed_path = self.cache_dir / filename
            content = compressed_path.read_bytes() if compressed_path.exists() else b""
            if (
                len(content) != compressed_size
                or hashlib.sha256(content).hexdigest() != expected_hash
            ):
                artifact_response = httpx.get(
                    artifact_url,
                    timeout=httpx.Timeout(20.0, connect=3.0),
                )
                artifact_response.raise_for_status()
                content = artifact_response.content
            if len(content) != compressed_size:
                raise ValueError(f"Taxonomy compressed-size mismatch for {artifact_url}")
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise ValueError(f"Taxonomy hash mismatch for {artifact_url}")
            raw = zstandard.ZstdDecompressor().decompress(
                content,
                max_output_size=uncompressed_size,
            )
            if len(raw) != uncompressed_size:
                raise ValueError(f"Taxonomy uncompressed-size mismatch for {artifact_url}")
            temporary_compressed = compressed_path.with_suffix(compressed_path.suffix + ".tmp")
            temporary_compressed.write_bytes(content)
            temporary_compressed.replace(compressed_path)
            sqlite_path = compressed_path.with_suffix("")
            temporary_sqlite = sqlite_path.with_suffix(sqlite_path.suffix + ".tmp")
            temporary_sqlite.write_bytes(raw)
            _validate_sqlite_artifact(temporary_sqlite, logical)
            temporary_sqlite.replace(sqlite_path)
            sqlite_paths[logical] = sqlite_path

        candidate = SQLiteTaxonomySnapshot(snapshot_revision, sqlite_paths)
        temporary_manifest = self.cache_dir / "manifest.json.tmp"
        temporary_manifest.write_text(
            json.dumps(manifest, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_manifest.replace(self.cache_dir / "manifest.json")
        with self._lock:
            previous = self._snapshot
            self._snapshot = candidate
            self._forced_revision = None
        if isinstance(previous, SQLiteTaxonomySnapshot):
            previous.close()
        return True

    def load_directory(self, directory: Path) -> bool:
        """Activate a fully downloaded schema-v2 SQLite package."""
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if int(manifest.get("schemaVersion") or 0) != 2:
            raise ValueError("Only schema-v2 SQLite taxonomy packages are supported")
        paths: dict[tuple[str, ...], Path] = {}
        for logical, descriptor in _manifest_artifacts(manifest):
            filename = Path(str(descriptor["url"])).name
            path = directory / filename.removesuffix(".zst")
            if not path.is_file():
                raise ValueError(f"Missing taxonomy SQLite artifact: {filename}")
            _validate_sqlite_artifact(path, logical)
            paths[logical] = path
        candidate = SQLiteTaxonomySnapshot(
            int(manifest.get("snapshotRevision") or 0), paths,
        )
        with self._lock:
            previous = self._snapshot
            self._snapshot = candidate
            self._forced_revision = None
        if isinstance(previous, SQLiteTaxonomySnapshot):
            previous.close()
        return True


class CompositeTaxonomySnapshot:
    """Immutable base plus complete-record delta overlay and tombstones."""

    def __init__(
        self,
        base,
        revision: int,
        overlay_records: dict[tuple[str, str], TaxonomyRecord],
        deleted: set[tuple[str, str]],
    ):
        self.base = base
        self.revision = str(revision)
        self.overlay_records = dict(overlay_records)
        self.deleted = frozenset(deleted)
        self.replaced = frozenset(self.overlay_records)
        self.overlay = TaxonomySnapshot(self.revision, self.overlay_records.values())
        self.record_count = getattr(base, "record_count", len(getattr(base, "records", ())))
        self.records = range(self.record_count + len(self.overlay_records))

    @staticmethod
    def _key(entity: ResolvedEntity) -> tuple[str, str]:
        return (entity.entity_type, str(entity.entity_id or entity.canonical_value))

    def _suppressed(self, entity: ResolvedEntity) -> bool:
        key = self._key(entity)
        return key in self.deleted or key in self.replaced

    def exact(self, text: str, excluded: list[tuple[int, int]] | None = None):
        candidates = list(self.overlay.exact(text, excluded))
        candidates.extend(
            item for item in self.base.exact(text, excluded)
            if not self._suppressed(item)
        )
        grouped: dict[tuple[int, int], list[ResolvedEntity]] = {}
        for item in candidates:
            grouped.setdefault((item.start, item.end), []).append(item)
        candidates = [items[0] for items in grouped.values() if len({self._key(i) for i in items}) == 1]
        candidates.sort(key=lambda item: (-(item.end - item.start), item.start))
        accepted: list[ResolvedEntity] = []
        for item in candidates:
            if not any(item.start < other.end and item.end > other.start for other in accepted):
                accepted.append(item)
        return sorted(accepted, key=lambda item: item.start)

    def ambiguous(self, text: str, excluded: list[tuple[int, int]] | None = None):
        references = []
        for source in (self.overlay, self.base):
            for reference in source.ambiguous(text, excluded):
                candidates = tuple(
                    candidate for candidate in reference.candidates
                    if (candidate.entity_type, str(candidate.entity_id or candidate.canonical_value))
                    not in self.deleted
                    and (
                        source is self.overlay
                        or (candidate.entity_type, str(candidate.entity_id or candidate.canonical_value))
                        not in self.replaced
                    )
                )
                if len(candidates) > 1:
                    references.append(AmbiguousReference(
                        reference.phrase, candidates, reference.start, reference.end
                    ))
        return references

    def fuzzy_match(self, phrase: str, entity_type: str, *, minimum_score: int | None = None):
        candidates = []
        overlay = self.overlay.fuzzy_match(phrase, entity_type, minimum_score=minimum_score)
        if overlay is not None:
            candidates.append(overlay)
        base = self.base.fuzzy_match(phrase, entity_type, minimum_score=minimum_score)
        if base is not None and not self._suppressed(base):
            candidates.append(base)
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[0].confidence - candidates[1].confidence < 0.03:
            return None
        return candidates[0]

    def facet_aliases(self, phrase: str, limit: int = 30):
        result = []
        seen = set()
        for source, is_base in ((self.overlay, False), (self.base, True)):
            for entity_type, alias, record in source.facet_aliases(phrase, limit):
                key = (entity_type, str(record.entity_id or record.canonical))
                if key in seen or key in self.deleted or (is_base and key in self.replaced):
                    continue
                seen.add(key)
                result.append((entity_type, alias, record))
                if len(result) >= limit:
                    return tuple(result)
        return tuple(result)

    def fuzzy_alias_items(self, entity_type: str):
        items = list(self.overlay.fuzzy_alias_items(entity_type))
        for alias, record in self.base.fuzzy_alias_items(entity_type):
            key = (entity_type, str(record.entity_id or record.canonical))
            if key not in self.deleted and key not in self.replaced:
                items.append((alias, record))
        return tuple(items)

taxonomy_manager = TaxonomyManager()
