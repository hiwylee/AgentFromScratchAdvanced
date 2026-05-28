"""Compact schema context loading, validation, retrieval, and masking."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_METADATA_VERSION = "agent-runtime.schema-metadata.v1"
CURATED_SEED_VERSION = "agent-runtime.curated-schema-seed.v1"
MASKING_POLICY_VERSION = "agent-runtime.sample-masking.v1"


class SchemaContextError(ValueError):
    """Raised when schema metadata and curated seed artifacts are invalid."""


@dataclass(frozen=True)
class SchemaProfileConfig:
    profile_id: str
    schema_owner: str
    metadata_path: Path
    seed_path: Path
    required_tables: frozenset[str]
    grant_profile: str


def load_schema_profile_from_manifest(
    profile_id: str,
    manifest_path: Path,
    *,
    project_root: Path | None = None,
) -> SchemaProfileConfig:
    """Load a schema profile config from artifact-manifest.v1.json."""
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)
    profiles = manifest.get("schema_profiles", {})
    if profile_id not in profiles:
        raise SchemaContextError(
            f"Schema profile {profile_id!r} not found in manifest {manifest_path}"
        )
    entry = profiles[profile_id]
    base = project_root if project_root is not None else manifest_path.parent.parent
    return SchemaProfileConfig(
        profile_id=str(entry["profile_id"]),
        schema_owner=str(entry["schema_owner"]),
        metadata_path=base / entry["metadata_path"],
        seed_path=base / entry["seed_path"],
        required_tables=frozenset(str(t) for t in entry["required_tables"]),
        grant_profile=str(entry["grant_profile"]),
    )


SENSITIVE_COLUMN_TOKENS = (
    "name",
    "email",
    "phone",
    "address",
    "ssn",
    "birth",
    "password",
    "token",
    "key",
    "secret",
)

IDENTIFIER_TOKENS = ("id", "identifier", "guid", "uuid", "key", "code")


@dataclass(frozen=True)
class SchemaArtifacts:
    metadata: dict[str, Any]
    seed: dict[str, Any]
    metadata_path: str
    seed_path: str
    table_by_id: dict[str, dict[str, Any]]
    seed_table_by_id: dict[str, dict[str, Any]]

    @property
    def profile_id(self) -> str:
        return str(self.metadata["profile_id"])

    @property
    def metadata_artifact_id(self) -> str:
        return _artifact_id(self.metadata, self.metadata_path)

    @property
    def seed_artifact_id(self) -> str:
        return _artifact_id(self.seed, self.seed_path)


@dataclass(frozen=True)
class CompactSchemaResult:
    profile_id: str
    schema_metadata_artifact_id: str
    curated_seed_artifact_id: str
    schema_metadata_version: str
    curated_seed_version: str
    masking_policy_version: str
    request_terms: list[str]
    selected_table_ids: list[str]
    context: dict[str, Any]
    considered_tables: list[dict[str, Any]]
    rejected_tables: list[dict[str, Any]]
    glossary_matches: list[dict[str, Any]]
    clarification: dict[str, Any]
    sample_values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_schema_artifacts(
    metadata_path: str | Path,
    seed_path: str | Path,
    *,
    expected_profile_id: str | None = None,
) -> SchemaArtifacts:
    """Load and validate schema metadata and curated seed JSON artifacts."""

    metadata_path = Path(metadata_path)
    seed_path = Path(seed_path)
    metadata = _read_json(metadata_path)
    seed = _read_json(seed_path)

    _validate_required_value(metadata, "schema_version", SCHEMA_METADATA_VERSION, "metadata")
    _validate_required_value(seed, "schema_version", CURATED_SEED_VERSION, "seed")

    metadata_profile = metadata.get("profile_id")
    seed_profile = seed.get("profile_id")
    if not metadata_profile or metadata_profile != seed_profile:
        raise SchemaContextError(
            f"profile_id mismatch: metadata={metadata_profile!r} seed={seed_profile!r}"
        )
    if expected_profile_id is not None and metadata_profile != expected_profile_id:
        raise SchemaContextError(
            f"profile_id mismatch: expected={expected_profile_id!r} actual={metadata_profile!r}"
        )

    table_by_id = _table_index(metadata)
    seed_table_by_id = _seed_table_index(seed)
    artifacts = SchemaArtifacts(
        metadata=metadata,
        seed=seed,
        metadata_path=str(metadata_path),
        seed_path=str(seed_path),
        table_by_id=table_by_id,
        seed_table_by_id=seed_table_by_id,
    )
    validate_schema_artifacts(artifacts)
    return artifacts


def validate_schema_artifacts(artifacts: SchemaArtifacts) -> None:
    """Validate seed references against the metadata snapshot."""

    for table in artifacts.metadata.get("tables", []):
        table_id = table.get("table_id")
        if not table_id:
            raise SchemaContextError("metadata table missing table_id")
        columns = _column_index(table)
        for relationship in table.get("relationships", []):
            to_table_id = relationship.get("to_table_id")
            if to_table_id not in artifacts.table_by_id:
                raise SchemaContextError(
                    f"relationship from {table_id} references missing table {to_table_id!r}"
                )
            _validate_columns_exist(
                table_id,
                columns,
                relationship.get("from_columns", []),
                "relationship from_columns",
            )
            _validate_columns_exist(
                to_table_id,
                _column_index(artifacts.table_by_id[to_table_id]),
                relationship.get("to_columns", []),
                "relationship to_columns",
            )

    for seed_table in artifacts.seed.get("tables", []):
        table_id = seed_table.get("table_id")
        if table_id not in artifacts.table_by_id:
            raise SchemaContextError(f"seed table references missing table {table_id!r}")
        columns = _column_index(artifacts.table_by_id[table_id])
        _validate_columns_exist(
            table_id,
            columns,
            seed_table.get("default_measures", []),
            "default_measures",
        )
        _validate_columns_exist(
            table_id,
            columns,
            seed_table.get("default_time_columns", []),
            "default_time_columns",
        )
        for join_table_id in seed_table.get("common_joins", []):
            if join_table_id not in artifacts.table_by_id:
                raise SchemaContextError(
                    f"seed table {table_id} common_joins references missing table {join_table_id!r}"
                )

    for entry in artifacts.seed.get("glossary", []):
        for mapping in entry.get("maps_to", []):
            table_id = mapping.get("table_id")
            column = mapping.get("column")
            if table_id not in artifacts.table_by_id:
                raise SchemaContextError(
                    f"glossary term {entry.get('term')!r} references missing table {table_id!r}"
                )
            _validate_columns_exist(
                table_id,
                _column_index(artifacts.table_by_id[table_id]),
                [column],
                f"glossary term {entry.get('term')!r}",
            )

    for allowlist in artifacts.seed.get("sample_value_allowlist", []):
        table_id = allowlist.get("table_id")
        if table_id not in artifacts.table_by_id:
            raise SchemaContextError(
                f"sample_value_allowlist references missing table {table_id!r}"
            )
        _validate_columns_exist(
            table_id,
            _column_index(artifacts.table_by_id[table_id]),
            allowlist.get("columns", []),
            "sample_value_allowlist",
        )


def build_compact_schema_context(
    artifacts: SchemaArtifacts,
    *,
    request_text: str = "",
    request_terms: Iterable[str] | None = None,
    table_limit: int = 6,
    relationship_limit: int = 2,
    min_score: int = 15,
) -> CompactSchemaResult:
    """Build compact schema context using deterministic lexical retrieval."""

    terms = extract_request_terms(request_text, request_terms)
    scored = [
        _score_table(table_id, table, artifacts, terms)
        for table_id, table in artifacts.table_by_id.items()
    ]
    scored.sort(key=lambda item: _score_sort_key(item, artifacts))

    top_score = scored[0]["score"] if scored else 0
    top_tied = [item for item in scored if item["score"] == top_score and top_score >= min_score]
    clarification = _clarification_state(top_score, top_tied, min_score)
    selected: list[str] = []
    selected_reasons: dict[str, list[str]] = {}

    if not clarification["required"]:
        for item in scored:
            if item["score"] < min_score or len(selected) >= table_limit:
                continue
            selected.append(item["table_id"])
            selected_reasons[item["table_id"]] = list(item["reasons"])
        _expand_relationships(
            selected,
            selected_reasons,
            artifacts,
            max_added=relationship_limit,
            table_limit=table_limit,
        )

    selected_set = set(selected)
    considered = [_considered_table(item, artifacts, selected_set) for item in scored]
    rejected = [
        {
            "table_id": item["table_id"],
            "score": item["score"],
            "reasons": item["reasons"] or ["no_lexical_match"],
            "rejection_reason": _rejection_reason(item, selected_set, min_score, clarification),
        }
        for item in scored
        if item["table_id"] not in selected_set
    ]

    sample_context = build_sample_value_context(artifacts.metadata, artifacts.seed)
    context = _expanded_context(artifacts, selected, selected_reasons, sample_context)

    return CompactSchemaResult(
        profile_id=artifacts.profile_id,
        schema_metadata_artifact_id=artifacts.metadata_artifact_id,
        curated_seed_artifact_id=artifacts.seed_artifact_id,
        schema_metadata_version=str(artifacts.metadata["schema_version"]),
        curated_seed_version=str(artifacts.seed["schema_version"]),
        masking_policy_version=MASKING_POLICY_VERSION,
        request_terms=terms,
        selected_table_ids=selected,
        context=context,
        considered_tables=considered,
        rejected_tables=rejected,
        glossary_matches=_glossary_matches(artifacts, terms),
        clarification=clarification,
        sample_values=sample_context,
    )


def extract_request_terms(
    request_text: str = "",
    request_terms: Iterable[str] | None = None,
) -> list[str]:
    """Normalize free text and caller-provided intent terms for retrieval."""

    terms: set[str] = set()
    for term in request_terms or []:
        normalized = _normalize_phrase(str(term))
        if normalized:
            terms.add(normalized)

    normalized_text = _normalize_phrase(request_text)
    if normalized_text:
        terms.add(normalized_text)
    tokens = _token_list(request_text)
    terms.update(tokens)
    for left, right in zip(tokens, tokens[1:]):
        terms.add(f"{left} {right}")

    return sorted(terms)


def build_sample_value_context(
    metadata: dict[str, Any],
    seed: dict[str, Any],
    sample_values: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    """Return sample values allowed for context plus explicit masking reasons."""

    sample_values = sample_values or _sample_values_from_metadata(metadata)
    table_by_id = _table_index(metadata)
    allowlist = _sample_allowlist(seed)
    included: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for table_id, columns in sample_values.items():
        table = table_by_id.get(table_id, {"columns": []})
        column_by_name = _column_index(table)
        for raw_column_name, values in sorted(columns.items()):
            column_name = _canonical_column_name(column_by_name, raw_column_name)
            column = column_by_name.get(column_name.upper(), {"name": column_name})
            allowed = allowlist.get(table_id, {}).get(column_name.upper())
            decision = sample_value_decision(table_id, column, allowed)
            capped_values = list(values[: decision["max_values"]])
            entry = {
                "table_id": table_id,
                "column": column_name,
                "reason": decision["reason"],
            }
            if decision["allowed"]:
                included.append({**entry, "values": capped_values})
            else:
                rejected.append(
                    {
                        **entry,
                        "masked_placeholder": f"<masked:{decision['reason']}>",
                        "masked_value_count": len(values),
                    }
                )

    return {
        "policy_version": MASKING_POLICY_VERSION,
        "included": included,
        "rejected": rejected,
    }


def sample_value_decision(
    table_id: str,
    column: dict[str, Any],
    allowlist_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Decide whether sample values may be exposed for one table column."""

    if allowlist_entry is None:
        return {"allowed": False, "reason": "not_allowlisted", "max_values": 0}
    if is_sensitive_column(column):
        return {"allowed": False, "reason": "sensitive_column", "max_values": 0}
    if is_high_cardinality_column(column):
        return {"allowed": False, "reason": "high_cardinality", "max_values": 0}
    max_values = int(allowlist_entry.get("max_values", 20))
    return {
        "allowed": True,
        "reason": allowlist_entry.get("reason", "allowlisted_business_category"),
        "max_values": max(0, min(max_values, 20)),
    }


def is_sensitive_column(column: dict[str, Any]) -> bool:
    """Return true when a column name or comment indicates sensitive data."""

    text = " ".join(
        str(column.get(key, ""))
        for key in ("name", "description", "comment", "comments", "semantic_type")
    ).casefold()
    tokens = set(_tokens(text))
    return any(token in tokens or token in text for token in SENSITIVE_COLUMN_TOKENS)


def is_high_cardinality_column(column: dict[str, Any]) -> bool:
    """Return true for identifiers, keys, and explicitly high-cardinality columns."""

    policy = str(column.get("sample_policy", "")).casefold()
    if policy in {"identifier", "high_cardinality", "never", "no_samples"}:
        return True
    semantic_type = str(column.get("semantic_type", "")).casefold()
    if semantic_type in {"identifier", "primary_key", "foreign_key", "high_cardinality"}:
        return True
    name_tokens = set(_tokens(str(column.get("name", ""))))
    return any(token in name_tokens for token in IDENTIFIER_TOKENS)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SchemaContextError(f"JSON artifact must be an object: {path}")
    return value


def _validate_required_value(
    artifact: dict[str, Any],
    key: str,
    expected: str,
    artifact_name: str,
) -> None:
    actual = artifact.get(key)
    if actual != expected:
        raise SchemaContextError(
            f"{artifact_name} {key} must be {expected!r}, got {actual!r}"
        )


def _table_index(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = metadata.get("tables", [])
    if not isinstance(tables, list):
        raise SchemaContextError("metadata tables must be a list")
    table_by_id: dict[str, dict[str, Any]] = {}
    for table in tables:
        table_id = table.get("table_id")
        if not table_id:
            raise SchemaContextError("metadata table missing table_id")
        if table_id in table_by_id:
            raise SchemaContextError(f"duplicate metadata table_id {table_id!r}")
        table_by_id[table_id] = table
    return table_by_id


def _seed_table_index(seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    table_by_id: dict[str, dict[str, Any]] = {}
    for table in seed.get("tables", []):
        table_id = table.get("table_id")
        if not table_id:
            raise SchemaContextError("seed table missing table_id")
        if table_id in table_by_id:
            raise SchemaContextError(f"duplicate seed table_id {table_id!r}")
        table_by_id[table_id] = table
    return table_by_id


def _column_index(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(column.get("name", "")).upper(): column
        for column in table.get("columns", [])
        if column.get("name")
    }


def _validate_columns_exist(
    table_id: str,
    columns: dict[str, dict[str, Any]],
    requested_columns: Iterable[Any],
    context: str,
) -> None:
    for column in requested_columns:
        if not column:
            raise SchemaContextError(f"{context} on {table_id} includes an empty column")
        if str(column).upper() not in columns:
            raise SchemaContextError(
                f"{context} references missing column {table_id}.{column}"
            )


def _score_table(
    table_id: str,
    table: dict[str, Any],
    artifacts: SchemaArtifacts,
    terms: list[str],
) -> dict[str, Any]:
    seed_table = artifacts.seed_table_by_id.get(table_id, {})
    reasons: list[str] = []
    score = 0

    curated_aliases = _normalized_values(seed_table.get("aliases", []))
    glossary_aliases = _table_glossary_aliases(artifacts, table_id)
    table_names = _normalized_values(
        [table_id, table.get("name", ""), *table.get("synonyms", [])]
    )
    column_names = _column_names(table)
    descriptions = _description_phrases(table, seed_table)
    searchable_tokens = _searchable_tokens(table, seed_table, glossary_aliases)

    for term in terms:
        variants = _term_variants(term)
        if variants & (curated_aliases | glossary_aliases):
            score += 100
            reasons.append(f"exact_curated_or_glossary_alias:{term}")
        if variants & table_names:
            score += 80
            reasons.append(f"exact_table_or_synonym:{term}")
        if variants & column_names:
            score += 60
            reasons.append(f"exact_column_or_alias:{term}")
        if _description_match(term, descriptions):
            score += 40
            reasons.append(f"description_phrase:{term}")
        token_matches = _tokens(term) & searchable_tokens
        if token_matches:
            score += 15 * len(token_matches)
            reasons.append(f"partial_token:{','.join(sorted(token_matches))}")

    return {
        "table_id": table_id,
        "score": score,
        "reasons": sorted(set(reasons)),
    }


def _score_sort_key(item: dict[str, Any], artifacts: SchemaArtifacts) -> tuple[Any, ...]:
    table_id = item["table_id"]
    table = artifacts.table_by_id[table_id]
    seed_table = artifacts.seed_table_by_id.get(table_id, {})
    priority = seed_table.get("priority") or table.get("curated_priority")
    primary_rank = 1 if priority == "primary" else 0
    density = len(table.get("relationships", [])) + len(seed_table.get("common_joins", []))
    return (-item["score"], -primary_rank, -density, table_id)


def _clarification_state(
    top_score: int,
    top_tied: list[dict[str, Any]],
    min_score: int,
) -> dict[str, Any]:
    if top_score < min_score:
        return {
            "required": True,
            "reason": "weak_schema_match",
            "candidate_table_ids": [item["table_id"] for item in top_tied],
        }
    if len(top_tied) > 1:
        return {
            "required": True,
            "reason": "ambiguous_schema_match",
            "candidate_table_ids": [item["table_id"] for item in top_tied],
        }
    return {"required": False, "reason": None, "candidate_table_ids": []}


def _expand_relationships(
    selected: list[str],
    selected_reasons: dict[str, list[str]],
    artifacts: SchemaArtifacts,
    *,
    max_added: int,
    table_limit: int,
) -> None:
    candidates: set[str] = set()
    for table_id in selected:
        seed_table = artifacts.seed_table_by_id.get(table_id, {})
        candidates.update(seed_table.get("common_joins", []))
        table = artifacts.table_by_id[table_id]
        candidates.update(
            relationship.get("to_table_id")
            for relationship in table.get("relationships", [])
            if relationship.get("to_table_id")
        )
        candidates.update(
            other_id
            for other_id, other in artifacts.table_by_id.items()
            for relationship in other.get("relationships", [])
            if relationship.get("to_table_id") == table_id
        )

    ranked = [
        {"table_id": table_id, "score": 10, "reasons": ["relationship_expansion"]}
        for table_id in candidates
        if table_id in artifacts.table_by_id and table_id not in selected
    ]
    ranked.sort(key=lambda item: _score_sort_key(item, artifacts))
    for item in ranked[:max_added]:
        if len(selected) >= table_limit:
            break
        selected.append(item["table_id"])
        selected_reasons[item["table_id"]] = list(item["reasons"])


def _expanded_context(
    artifacts: SchemaArtifacts,
    selected: list[str],
    selected_reasons: dict[str, list[str]],
    sample_context: dict[str, Any],
) -> dict[str, Any]:
    selected_set = set(selected)
    included_samples = {
        (item["table_id"], item["column"]): item for item in sample_context["included"]
    }
    tables = []
    for table_id in selected:
        table = artifacts.table_by_id[table_id]
        seed_table = artifacts.seed_table_by_id.get(table_id, {})
        table_samples = [
            item
            for (sample_table_id, _), item in included_samples.items()
            if sample_table_id == table_id
        ]
        tables.append(
            {
                "table_id": table_id,
                "owner": table.get("owner"),
                "name": table.get("name"),
                "kind": table.get("kind"),
                "role": seed_table.get("role", table.get("role")),
                "description": table.get("description") or table.get("comment"),
                "synonyms": table.get("synonyms", []),
                "curated": {
                    "priority": seed_table.get("priority", table.get("curated_priority")),
                    "aliases": seed_table.get("aliases", []),
                    "default_measures": seed_table.get("default_measures", []),
                    "default_time_columns": seed_table.get("default_time_columns", []),
                    "notes": seed_table.get("notes"),
                },
                "columns": table.get("columns", []),
                "relationships": [
                    relationship
                    for relationship in table.get("relationships", [])
                    if relationship.get("to_table_id") in selected_set
                ],
                "glossary": _glossary_for_table(artifacts, table_id),
                "sample_values": table_samples,
                "retrieval_reasons": selected_reasons.get(table_id, []),
            }
        )
    return {"tables": tables}


def _considered_table(
    item: dict[str, Any],
    artifacts: SchemaArtifacts,
    selected_set: set[str],
) -> dict[str, Any]:
    table_id = item["table_id"]
    table = artifacts.table_by_id[table_id]
    seed_table = artifacts.seed_table_by_id.get(table_id, {})
    return {
        "table_id": table_id,
        "score": item["score"],
        "selected": table_id in selected_set,
        "reasons": item["reasons"] or ["no_lexical_match"],
        "tie_break": {
            "priority": seed_table.get("priority", table.get("curated_priority")),
            "relationship_density": len(table.get("relationships", []))
            + len(seed_table.get("common_joins", [])),
            "lexicographic": table_id,
        },
    }


def _rejection_reason(
    item: dict[str, Any],
    selected_set: set[str],
    min_score: int,
    clarification: dict[str, Any],
) -> str:
    if clarification["required"]:
        return str(clarification["reason"])
    if item["score"] < min_score:
        return "score_below_threshold"
    if item["table_id"] not in selected_set:
        return "not_selected_table_limit"
    return "selected"


def _glossary_matches(artifacts: SchemaArtifacts, terms: list[str]) -> list[dict[str, Any]]:
    matches = []
    for entry in artifacts.seed.get("glossary", []):
        aliases = _normalized_values([entry.get("term"), *entry.get("aliases", [])])
        matched_terms = sorted(term for term in terms if _term_variants(term) & aliases)
        if matched_terms:
            matches.append(
                {
                    "term": entry.get("term"),
                    "aliases": entry.get("aliases", []),
                    "matched_terms": matched_terms,
                    "maps_to": entry.get("maps_to", []),
                    "ambiguity": entry.get("ambiguity"),
                }
            )
    return matches


def _glossary_for_table(
    artifacts: SchemaArtifacts,
    table_id: str,
) -> list[dict[str, Any]]:
    entries = []
    for entry in artifacts.seed.get("glossary", []):
        maps_to = [
            mapping
            for mapping in entry.get("maps_to", [])
            if mapping.get("table_id") == table_id
        ]
        if maps_to:
            entries.append(
                {
                    "term": entry.get("term"),
                    "aliases": entry.get("aliases", []),
                    "maps_to": maps_to,
                    "ambiguity": entry.get("ambiguity"),
                }
            )
    return entries


def _table_glossary_aliases(artifacts: SchemaArtifacts, table_id: str) -> set[str]:
    aliases: set[str] = set()
    for entry in artifacts.seed.get("glossary", []):
        if any(mapping.get("table_id") == table_id for mapping in entry.get("maps_to", [])):
            aliases.update(_normalized_values([entry.get("term"), *entry.get("aliases", [])]))
    return aliases


def _column_names(table: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for column in table.get("columns", []):
        names.update(_normalized_values([column.get("name"), *column.get("aliases", [])]))
        names.update(_normalized_values(column.get("business_terms", [])))
    return names


def _description_phrases(
    table: dict[str, Any],
    seed_table: dict[str, Any],
) -> list[str]:
    values = [table.get("description"), table.get("comment"), table.get("comments"), seed_table.get("notes")]
    for column in table.get("columns", []):
        values.extend(
            [
                column.get("description"),
                column.get("comment"),
                column.get("comments"),
                *column.get("business_terms", []),
            ]
        )
    return [_normalize_phrase(value) for value in values if value]


def _description_match(term: str, descriptions: list[str]) -> bool:
    if len(term) < 3:
        return False
    variants = _term_variants(term)
    return any(variant in description for description in descriptions for variant in variants)


def _searchable_tokens(
    table: dict[str, Any],
    seed_table: dict[str, Any],
    glossary_aliases: set[str],
) -> set[str]:
    values: list[Any] = [
        table.get("table_id"),
        table.get("name"),
        table.get("description"),
        table.get("comment"),
        *table.get("synonyms", []),
        *seed_table.get("aliases", []),
        seed_table.get("notes"),
        *glossary_aliases,
    ]
    for column in table.get("columns", []):
        values.extend(
            [
                column.get("name"),
                column.get("description"),
                column.get("comment"),
                *column.get("business_terms", []),
            ]
        )
    tokens: set[str] = set()
    for value in values:
        tokens.update(_tokens(str(value)))
    return tokens


def _sample_values_from_metadata(metadata: dict[str, Any]) -> dict[str, dict[str, list[Any]]]:
    samples: dict[str, dict[str, list[Any]]] = {}
    for table in metadata.get("tables", []):
        table_id = table.get("table_id")
        for column in table.get("columns", []):
            if "sample_values" in column:
                samples.setdefault(table_id, {})[column["name"]] = list(column["sample_values"])
    return samples


def _sample_allowlist(seed: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    allowlist: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in seed.get("sample_value_allowlist", []):
        table_id = entry.get("table_id")
        for column in entry.get("columns", []):
            allowlist.setdefault(table_id, {})[str(column).upper()] = entry
    return allowlist


def _canonical_column_name(
    column_by_name: dict[str, dict[str, Any]],
    raw_column_name: str,
) -> str:
    column = column_by_name.get(str(raw_column_name).upper())
    if column is None:
        return str(raw_column_name)
    return str(column.get("name", raw_column_name))


def _normalized_values(values: Iterable[Any]) -> set[str]:
    normalized = set()
    for value in values:
        phrase = _normalize_phrase(str(value)) if value is not None else ""
        if phrase:
            normalized.add(phrase)
            normalized.update(_term_variants(phrase))
    return normalized


def _term_variants(term: str) -> set[str]:
    variants = {_normalize_phrase(term)}
    tokens = _tokens(term)
    if len(tokens) == 1:
        token = next(iter(tokens))
        variants.add(_singular(token))
    return {variant for variant in variants if variant}


def _tokens(value: str) -> set[str]:
    return set(_token_list(value))


def _token_list(value: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9]+", value.casefold().replace("_", " ")):
        token = _singular(match.group(0))
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _normalize_phrase(value: str) -> str:
    return " ".join(_token_list(value))


def _artifact_id(artifact: dict[str, Any], fallback_path: str) -> str:
    source = artifact.get("source", {})
    for key in ("artifact_id", "id", "name"):
        if source.get(key):
            return str(source[key])
    return Path(fallback_path).name
