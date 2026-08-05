from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz

try:
    import jellyfish
except ImportError:  # pragma: no cover - deployment dependency supplies it
    jellyfish = None

from src.resolver.models import (
    AmbiguousCandidate,
    AmbiguousReference,
    ResolvedEntity,
)

_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.I)
_TYPE_NAMES = {1: "creator", 2: "publication", 3: "organization", 4: "location"}
_NON_ENTITY_ALIASES = {
    "a", "an", "and", "by", "for", "from", "in", "latest", "near",
    "new", "of", "on", "play", "recent", "the", "to",
}
_TYPE_PRIORITY = {"organization": 0, "publication": 1, "creator": 2, "location": 3}


def normalize_alias(value: str) -> str:
    return " ".join(match.group(0).lower() for match in _WORD.finditer(value))


def _fts_prefix_query(value: str) -> str:
    tokens = normalize_alias(value).split()
    return " AND ".join(f'"{token}"*' for token in tokens if token)


def _metadata(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro&immutable=1",
        uri=True,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA cache_size=-8000")
    return connection


@dataclass(frozen=True)
class _Route:
    entity_type: str
    entity_id: str
    canonical: str
    shard_id: str | None
    alias: str
    metadata: dict
    slug: str | None = None


class SQLiteTaxonomySnapshot:
    """Compatibility view exposing the resolver's snapshot query surface."""

    def __init__(self, revision: int, paths: dict[tuple[str, ...], Path]):
        self.revision = str(revision)
        self._paths = dict(paths)
        self.schema_version = 2
        self.artifact_count = len(paths)
        self.routing_artifact_count = sum(1 for logical in paths if logical[0] == "routing")
        self.shard_artifact_count = sum(1 for logical in paths if logical[0] == "shards")
        self._exact = _connect(self._required(("routing", "exact")))
        self._core = _connect(self._required(("routing", "core")))
        self._fuzzy = {
            logical[-1]: _connect(path)
            for logical, path in paths.items()
            if len(logical) == 3 and logical[:2] == ("routing", "fuzzy")
        }
        self._shard_paths = {
            (logical[1], logical[2]): path
            for logical, path in paths.items()
            if len(logical) == 3 and logical[0] == "shards"
        }
        self._shards: OrderedDict[tuple[str, str], sqlite3.Connection] = OrderedDict()
        self._shard_lock = threading.RLock()
        self._max_words = self._calculate_max_words()
        self.record_count = self._calculate_record_count()
        # Kept for old health/tests that call len(snapshot.records).
        self.records = range(self.record_count)

    def _required(self, logical: tuple[str, ...]) -> Path:
        path = self._paths.get(logical)
        if path is None:
            raise ValueError(f"Missing required taxonomy artifact: {'.'.join(logical)}")
        return path

    def _calculate_max_words(self) -> int:
        exact = self._exact.execute(
            "SELECT COALESCE(MAX(LENGTH(normalized_alias) - "
            "LENGTH(REPLACE(normalized_alias, ' ', '')) + 1), 1) FROM route_aliases"
        ).fetchone()[0]
        core = self._core.execute(
            "SELECT COALESCE(MAX(LENGTH(normalized_alias) - "
            "LENGTH(REPLACE(normalized_alias, ' ', '')) + 1), 1) FROM aliases"
        ).fetchone()[0]
        return min(max(int(exact), int(core), 1), 12)

    def _calculate_record_count(self) -> int:
        total = int(self._exact.execute("SELECT COUNT(*) FROM route_entities").fetchone()[0])
        total += int(self._core.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        return total

    def close(self) -> None:
        self._exact.close()
        self._core.close()
        for connection in self._fuzzy.values():
            connection.close()
        with self._shard_lock:
            for connection in self._shards.values():
                connection.close()
            self._shards.clear()

    def _span_phrases(self, text: str):
        words = list(_WORD.finditer(text))
        for start_index, first in enumerate(words):
            limit = min(self._max_words, len(words) - start_index)
            for count in range(1, limit + 1):
                last = words[start_index + count - 1]
                yield normalize_alias(text[first.start():last.end()]), first.start(), last.end()

    def _shard(self, entity_type: str, shard_id: str) -> sqlite3.Connection:
        key = (entity_type, shard_id)
        with self._shard_lock:
            current = self._shards.pop(key, None)
            if current is not None:
                self._shards[key] = current
                return current
            path = self._shard_paths.get(key)
            if path is None:
                raise ValueError(f"Missing routed taxonomy shard: {entity_type}/{shard_id}")
            current = _connect(path)
            self._shards[key] = current
            while len(self._shards) > 12:
                _, evicted = self._shards.popitem(last=False)
                evicted.close()
            return current

    def _hydrate(self, route: _Route) -> _Route:
        if not route.shard_id:
            return route
        row = self._shard(route.entity_type, route.shard_id).execute(
            "SELECT canonical, metadata_json FROM entities "
            "WHERE entity_type=? AND entity_id=?",
            (route.entity_type, route.entity_id),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Router references missing entity {route.entity_type}/{route.entity_id}"
            )
        return _Route(
            route.entity_type,
            route.entity_id,
            str(row["canonical"]),
            route.shard_id,
            route.alias,
            _metadata(row["metadata_json"]),
            route.slug,
        )

    def _routes(self, phrase: str) -> list[_Route]:
        compact = phrase.replace(" ", "")
        rows = self._exact.execute(
            "SELECT e.entity_type_code,e.entity_id,e.canonical,e.shard_id,a.normalized_alias "
            "FROM route_aliases a JOIN route_entities e ON e.entity_pk=a.entity_pk "
            "WHERE a.normalized_alias=? OR a.compact_alias=?",
            (phrase, compact),
        ).fetchall()
        routes = [
            _Route(
                _TYPE_NAMES[int(row["entity_type_code"])],
                str(row["entity_id"]),
                str(row["canonical"]),
                str(row["shard_id"]),
                str(row["normalized_alias"]),
                {},
            )
            for row in rows
        ]
        core_rows = self._core.execute(
            "SELECT e.entity_type,e.entity_id,e.canonical,e.slug,e.metadata_json,a.normalized_alias "
            "FROM aliases a JOIN entities e ON e.entity_type=a.entity_type "
            "AND e.entity_id=a.entity_id WHERE a.normalized_alias=?",
            (phrase,),
        ).fetchall()
        routes.extend(
            _Route(
                str(row["entity_type"]),
                str(row["entity_id"]),
                str(row["canonical"]),
                None,
                str(row["normalized_alias"]),
                _metadata(row["metadata_json"]),
                str(row["slug"]) if row["slug"] else None,
            )
            for row in core_rows
        )
        unique: dict[tuple[str, str], _Route] = {}
        for route in routes:
            unique[(route.entity_type, route.entity_id)] = route
        return list(unique.values())

    def _collapsed_routes(self, phrase: str) -> list[_Route]:
        """Collapse duplicate database identities into spoken entities.

        The compiler can legitimately contain multiple creator IDs with the
        same display name and a creator/organisation pair with the same spoken
        name. Alexa must hear one entity, while the search payload retains all
        equivalent IDs for the selected entity type.
        """
        grouped: dict[tuple[str, str], list[_Route]] = {}
        for route in self._routes(phrase):
            grouped.setdefault(
                (route.entity_type, route.canonical.strip().casefold()), []
            ).append(route)

        collapsed: list[_Route] = []
        for equivalents in grouped.values():
            primary = self._hydrate(equivalents[0])
            ids = tuple(dict.fromkeys(route.entity_id for route in equivalents))
            metadata = dict(primary.metadata)
            if len(ids) > 1:
                metadata["equivalentIds"] = ids
            collapsed.append(_Route(
                primary.entity_type,
                primary.entity_id,
                primary.canonical,
                primary.shard_id,
                primary.alias,
                metadata,
                primary.slug,
            ))

        # A compiler row may represent the same spoken owner as both a creator
        # and its organisation. Prefer the organisation; different canonical
        # names remain genuinely ambiguous.
        by_name: dict[str, _Route] = {}
        for route in collapsed:
            key = route.canonical.strip().casefold()
            current = by_name.get(key)
            if current is None or _TYPE_PRIORITY.get(route.entity_type, 99) < _TYPE_PRIORITY.get(current.entity_type, 99):
                by_name[key] = route
        routes = list(by_name.values())
        canonical_matches = [
            route for route in routes
            if normalize_alias(route.canonical) == normalize_alias(phrase)
        ]
        return canonical_matches or routes

    @staticmethod
    def _entity(route: _Route, original: str, start: int, end: int, confidence: float, method: str):
        route = route
        return ResolvedEntity(
            route.entity_type,
            route.entity_id,
            route.slug or route.canonical,
            original,
            confidence,
            method,
            start,
            end,
            route.metadata,
        )

    def exact(self, text: str, excluded: list[tuple[int, int]] | None = None) -> list[ResolvedEntity]:
        excluded = excluded or []
        proposals: list[ResolvedEntity] = []
        for phrase, start, end in self._span_phrases(text):
            if any(start < stop and end > begin for begin, stop in excluded):
                continue
            routes = self._collapsed_routes(phrase)
            if len(routes) != 1:
                continue
            route = routes[0]
            proposals.append(self._entity(route, text[start:end], start, end, 1.0, "exact"))
        proposals.sort(key=lambda item: (-(item.end - item.start), item.start))
        accepted: list[ResolvedEntity] = []
        for item in proposals:
            if not any(item.start < other.end and item.end > other.start for other in accepted):
                accepted.append(item)
        return sorted(accepted, key=lambda item: item.start)

    def ambiguous(self, text: str, excluded: list[tuple[int, int]] | None = None):
        excluded = excluded or []
        matches: list[AmbiguousReference] = []
        for phrase, start, end in self._span_phrases(text):
            if any(start < stop and end > begin for begin, stop in excluded):
                continue
            if phrase in _NON_ENTITY_ALIASES:
                continue
            routes = self._collapsed_routes(phrase)
            if len(routes) < 2:
                continue
            matches.append(AmbiguousReference(
                phrase=text[start:end],
                candidates=tuple(
                    AmbiguousCandidate(route.entity_type, route.entity_id, route.slug or route.canonical)
                    for route in routes
                ),
                start=start,
                end=end,
            ))
        matches.sort(key=lambda item: (-(item.end - item.start), item.start))
        accepted: list[AmbiguousReference] = []
        for item in matches:
            if not any(item.start < other.end and item.end > other.start for other in accepted):
                accepted.append(item)
        return sorted(accepted, key=lambda item: item.start)

    def _fuzzy_routes(self, phrase: str, entity_type: str, limit: int = 100) -> list[_Route]:
        connection = self._fuzzy.get(entity_type)
        if connection is None:
            return []
        normalized = normalize_alias(phrase)
        candidates: dict[int, sqlite3.Row] = {}
        if jellyfish is not None:
            key = jellyfish.metaphone(normalized)
            if key:
                for row in connection.execute(
                    "SELECT a.alias_pk,a.normalized_alias,e.entity_id,e.canonical,e.shard_id "
                    "FROM fuzzy_aliases a JOIN fuzzy_entities e ON e.entity_pk=a.entity_pk "
                    "WHERE a.phonetic_key=? LIMIT 30",
                    (key,),
                ):
                    candidates[int(row["alias_pk"])] = row
        prefix = _fts_prefix_query(normalized)
        if prefix:
            try:
                rows = connection.execute(
                    "SELECT a.alias_pk,a.normalized_alias,e.entity_id,e.canonical,e.shard_id "
                    "FROM fuzzy_prefix_fts f JOIN fuzzy_aliases a ON a.alias_pk=f.rowid "
                    "JOIN fuzzy_entities e ON e.entity_pk=a.entity_pk "
                    "WHERE fuzzy_prefix_fts MATCH ? ORDER BY bm25(fuzzy_prefix_fts) LIMIT 50",
                    (prefix,),
                )
                for row in rows:
                    candidates[int(row["alias_pk"])] = row
            except sqlite3.OperationalError:
                pass
        if len(normalized) >= 3:
            try:
                rows = connection.execute(
                    "SELECT a.alias_pk,a.normalized_alias,e.entity_id,e.canonical,e.shard_id "
                    "FROM fuzzy_trigram_fts f JOIN fuzzy_aliases a ON a.alias_pk=f.rowid "
                    "JOIN fuzzy_entities e ON e.entity_pk=a.entity_pk "
                    "WHERE fuzzy_trigram_fts MATCH ? ORDER BY bm25(fuzzy_trigram_fts) LIMIT 50",
                    (f'"{normalized}"',),
                )
                for row in rows:
                    candidates[int(row["alias_pk"])] = row
            except sqlite3.OperationalError:
                pass
        ranked = sorted(
            candidates.values(),
            key=lambda row: max(
                fuzz.ratio(normalized, str(row["normalized_alias"])),
                fuzz.WRatio(normalized, str(row["normalized_alias"])),
                fuzz.token_ratio(normalized, str(row["normalized_alias"])),
            ),
            reverse=True,
        )[:limit]
        return [
            _Route(
                entity_type,
                str(row["entity_id"]),
                str(row["canonical"]),
                str(row["shard_id"]),
                str(row["normalized_alias"]),
                {},
            )
            for row in ranked
        ]

    def fuzzy_match(self, phrase: str, entity_type: str, *, minimum_score: int | None = None):
        normalized = normalize_alias(phrase)
        routes = self._fuzzy_routes(normalized, entity_type)
        if not routes:
            return None
        scored: dict[str, tuple[_Route, float]] = {}
        for route in routes:
            score = max(
                fuzz.ratio(normalized, route.alias),
                fuzz.WRatio(normalized, route.alias),
                fuzz.token_ratio(normalized, route.alias),
            )
            current = scored.get(route.entity_id)
            if current is None or score > current[1]:
                scored[route.entity_id] = (route, score)
        ranked = sorted(scored.values(), key=lambda item: item[1], reverse=True)
        threshold = minimum_score if minimum_score is not None else 88
        if not ranked or ranked[0][1] < threshold:
            return None
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 3:
            return None
        route, score = ranked[0]
        route = self._hydrate(route)
        return self._entity(route, phrase, 0, len(phrase), score / 100.0, "fuzzy")

    def facet_aliases(self, phrase: str, limit: int = 30) -> Iterable[tuple[str, str, _Route]]:
        query = _fts_prefix_query(phrase)
        if not query:
            return ()
        try:
            rows = self._core.execute(
                "SELECT a.entity_type,a.entity_id,a.normalized_alias,e.canonical,e.slug,e.metadata_json "
                "FROM alias_fts_core f JOIN aliases a ON a.rowid=f.rowid "
                "JOIN entities e ON e.entity_type=a.entity_type AND e.entity_id=a.entity_id "
                "WHERE alias_fts_core MATCH ? AND a.entity_type IN ('category','tag') "
                "ORDER BY bm25(alias_fts_core) LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return ()
        return tuple(
            (
                str(row["entity_type"]),
                str(row["normalized_alias"]),
                _Route(
                    str(row["entity_type"]),
                    str(row["entity_id"]),
                    str(row["canonical"]),
                    None,
                    str(row["normalized_alias"]),
                    _metadata(row["metadata_json"]),
                    str(row["slug"]) if row["slug"] else None,
                ),
            )
            for row in rows
        )

    def fuzzy_alias_items(self, entity_type: str):
        connection = self._fuzzy.get(entity_type)
        if connection is None:
            return ()
        rows = connection.execute(
            "SELECT a.normalized_alias,e.entity_id,e.canonical,e.shard_id "
            "FROM fuzzy_aliases a JOIN fuzzy_entities e ON e.entity_pk=a.entity_pk"
        ).fetchall()
        return tuple(
            (
                str(row["normalized_alias"]),
                _Route(entity_type, str(row["entity_id"]), str(row["canonical"]), str(row["shard_id"]), str(row["normalized_alias"]), {}),
            )
            for row in rows
        )
