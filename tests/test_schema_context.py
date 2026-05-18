import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.schema_context import (
    CURATED_SEED_VERSION,
    SCHEMA_METADATA_VERSION,
    SchemaContextError,
    build_compact_schema_context,
    build_sample_value_context,
    load_schema_artifacts,
)


class SchemaContextTests(unittest.TestCase):
    def test_valid_seed_loads_and_retrieves_sales_product_trend_context(self):
        with self._artifacts() as (metadata_path, seed_path):
            artifacts = load_schema_artifacts(metadata_path, seed_path)

            result = build_compact_schema_context(
                artifacts,
                request_text="show revenue by product trend",
                request_terms=["revenue", "product", "trend"],
            )

            self.assertFalse(result.clarification["required"])
            self.assertIn("SH.SALES", result.selected_table_ids)
            self.assertIn("SH.PRODUCTS", result.selected_table_ids)
            self.assertIn("SH.TIMES", result.selected_table_ids)
            self.assertEqual("oracle_adw_sh.v1", result.profile_id)
            self.assertEqual(SCHEMA_METADATA_VERSION, result.schema_metadata_version)
            self.assertEqual(CURATED_SEED_VERSION, result.curated_seed_version)

            expanded_table_ids = [
                table["table_id"] for table in result.context["tables"]
            ]
            self.assertEqual(result.selected_table_ids, expanded_table_ids)
            glossary_terms = {entry["term"] for entry in result.glossary_matches}
            self.assertIn("revenue", glossary_terms)

    def test_missing_seed_table_fails_validation(self):
        with self._artifacts(seed_updates={"tables": [{"table_id": "SH.MISSING"}]}) as (
            metadata_path,
            seed_path,
        ):
            with self.assertRaisesRegex(SchemaContextError, "missing table"):
                load_schema_artifacts(metadata_path, seed_path)

    def test_missing_seed_column_fails_validation(self):
        seed_updates = {
            "tables": [
                {
                    "table_id": "SH.SALES",
                    "default_measures": ["MISSING_AMOUNT"],
                }
            ]
        }
        with self._artifacts(seed_updates=seed_updates) as (metadata_path, seed_path):
            with self.assertRaisesRegex(SchemaContextError, "missing column"):
                load_schema_artifacts(metadata_path, seed_path)

    def test_ambiguous_retrieval_requires_clarification(self):
        metadata_updates = {
            "tables": [
                *_base_metadata()["tables"],
                _table("SH.COUNTRIES", "COUNTRIES", "Region dimension.", ["REGION"]),
            ]
        }
        seed_updates = {
            "tables": [
                *_base_seed()["tables"],
                {
                    "table_id": "SH.COUNTRIES",
                    "role": "dimension",
                    "priority": "supporting",
                    "aliases": ["region"],
                },
            ]
        }
        with self._artifacts(
            metadata_updates=metadata_updates,
            seed_updates=seed_updates,
        ) as (metadata_path, seed_path):
            artifacts = load_schema_artifacts(metadata_path, seed_path)

            result = build_compact_schema_context(
                artifacts,
                request_text="region",
                request_terms=["region"],
            )

            self.assertTrue(result.clarification["required"])
            self.assertEqual("ambiguous_schema_match", result.clarification["reason"])
            self.assertEqual(
                ["SH.COUNTRIES", "SH.CUSTOMERS"],
                result.clarification["candidate_table_ids"],
            )
            self.assertEqual([], result.selected_table_ids)

    def test_sensitive_sample_values_are_masked_even_when_allowlisted(self):
        metadata = _base_metadata()
        seed = _base_seed()
        samples = {
            "SH.PRODUCTS": {
                "PROD_CATEGORY": ["Hardware", "Software", "Services"],
                "PROD_ID": [10, 11],
            },
            "SH.CUSTOMERS": {
                "CUSTOMER_NAME": ["Ada Lovelace"],
                "CUST_EMAIL": ["ada@example.test"],
            },
        }

        sample_context = build_sample_value_context(metadata, seed, samples)

        included = {
            (entry["table_id"], entry["column"]): entry
            for entry in sample_context["included"]
        }
        rejected = {
            (entry["table_id"], entry["column"]): entry
            for entry in sample_context["rejected"]
        }

        self.assertEqual(
            ["Hardware", "Software", "Services"],
            included[("SH.PRODUCTS", "PROD_CATEGORY")]["values"],
        )
        self.assertEqual(
            "high_cardinality",
            rejected[("SH.PRODUCTS", "PROD_ID")]["reason"],
        )
        self.assertEqual(
            "sensitive_column",
            rejected[("SH.CUSTOMERS", "CUSTOMER_NAME")]["reason"],
        )
        self.assertEqual(
            "sensitive_column",
            rejected[("SH.CUSTOMERS", "CUST_EMAIL")]["reason"],
        )
        self.assertNotIn("Ada Lovelace", str(sample_context))
        self.assertNotIn("ada@example.test", str(sample_context))

    def _artifacts(self, metadata_updates=None, seed_updates=None):
        return _ArtifactFiles(metadata_updates, seed_updates)


class _ArtifactFiles:
    def __init__(self, metadata_updates=None, seed_updates=None):
        self.metadata_updates = metadata_updates or {}
        self.seed_updates = seed_updates or {}
        self.tmp = tempfile.TemporaryDirectory()

    def __enter__(self):
        tmp_path = Path(self.tmp.name)
        metadata = _merge(_base_metadata(), self.metadata_updates)
        seed = _merge(_base_seed(), self.seed_updates)
        self.metadata_path = tmp_path / "metadata.json"
        self.seed_path = tmp_path / "seed.json"
        self.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        self.seed_path.write_text(json.dumps(seed), encoding="utf-8")
        return self.metadata_path, self.seed_path

    def __exit__(self, exc_type, exc, traceback):
        self.tmp.cleanup()


def _merge(base, updates):
    merged = json.loads(json.dumps(base))
    for key, value in updates.items():
        merged[key] = value
    return merged


def _base_metadata():
    return {
        "schema_version": SCHEMA_METADATA_VERSION,
        "profile_id": "oracle_adw_sh.v1",
        "source": {"artifact_id": "test-metadata"},
        "tables": [
            {
                "table_id": "SH.SALES",
                "owner": "SH",
                "name": "SALES",
                "kind": "table",
                "role": "fact",
                "description": "Sales fact table for revenue trend analysis.",
                "synonyms": ["SALES"],
                "curated_priority": "primary",
                "columns": [
                    _column("AMOUNT_SOLD", "Sales amount measure.", ["revenue"]),
                    _column("PROD_ID", "Product identifier.", semantic_type="foreign_key"),
                    _column("TIME_ID", "Time identifier.", semantic_type="foreign_key"),
                ],
                "relationships": [
                    {
                        "type": "foreign_key",
                        "from_columns": ["PROD_ID"],
                        "to_table_id": "SH.PRODUCTS",
                        "to_columns": ["PROD_ID"],
                    },
                    {
                        "type": "foreign_key",
                        "from_columns": ["TIME_ID"],
                        "to_table_id": "SH.TIMES",
                        "to_columns": ["TIME_ID"],
                    },
                ],
            },
            _table(
                "SH.PRODUCTS",
                "PRODUCTS",
                "Product dimension for product categories.",
                ["PROD_ID", "PROD_CATEGORY", "PROD_NAME"],
            ),
            _table(
                "SH.TIMES",
                "TIMES",
                "Calendar time dimension for trends.",
                ["TIME_ID", "CALENDAR_MONTH_DESC"],
            ),
            _table(
                "SH.CUSTOMERS",
                "CUSTOMERS",
                "Customer dimension with region and sensitive contact fields.",
                ["CUST_ID", "REGION", "CUSTOMER_NAME", "CUST_EMAIL"],
            ),
        ],
    }


def _base_seed():
    return {
        "schema_version": CURATED_SEED_VERSION,
        "profile_id": "oracle_adw_sh.v1",
        "source": {"artifact_id": "test-seed"},
        "tables": [
            {
                "table_id": "SH.SALES",
                "role": "fact",
                "priority": "primary",
                "aliases": ["sales"],
                "default_measures": ["AMOUNT_SOLD"],
                "default_time_columns": ["TIME_ID"],
                "common_joins": ["SH.PRODUCTS", "SH.TIMES", "SH.CUSTOMERS"],
            },
            {
                "table_id": "SH.PRODUCTS",
                "role": "dimension",
                "priority": "primary",
                "aliases": ["product"],
            },
            {
                "table_id": "SH.TIMES",
                "role": "dimension",
                "priority": "primary",
                "aliases": ["time", "month"],
            },
            {
                "table_id": "SH.CUSTOMERS",
                "role": "dimension",
                "priority": "supporting",
                "aliases": ["region"],
            },
        ],
        "glossary": [
            {
                "term": "revenue",
                "aliases": ["sales amount"],
                "maps_to": [
                    {
                        "table_id": "SH.SALES",
                        "column": "AMOUNT_SOLD",
                        "expression": "SUM(AMOUNT_SOLD)",
                    }
                ],
                "ambiguity": "low",
            },
            {
                "term": "product",
                "aliases": ["item"],
                "maps_to": [{"table_id": "SH.PRODUCTS", "column": "PROD_NAME"}],
                "ambiguity": "low",
            },
        ],
        "sample_value_allowlist": [
            {
                "table_id": "SH.PRODUCTS",
                "columns": ["PROD_CATEGORY", "PROD_ID"],
                "max_values": 20,
                "reason": "Low-risk product category values.",
            },
            {
                "table_id": "SH.CUSTOMERS",
                "columns": ["CUSTOMER_NAME", "CUST_EMAIL"],
                "max_values": 20,
                "reason": "Intentionally allowlisted to prove sensitive masking wins.",
            },
        ],
    }


def _table(table_id, name, description, column_names):
    return {
        "table_id": table_id,
        "owner": table_id.split(".")[0],
        "name": name,
        "kind": "table",
        "role": "dimension",
        "description": description,
        "synonyms": [name],
        "columns": [_column(column_name, f"{column_name} column.") for column_name in column_names],
        "relationships": [],
    }


def _column(name, description, business_terms=None, semantic_type=None):
    column = {
        "name": name,
        "data_type": "VARCHAR2",
        "nullable": True,
        "description": description,
        "business_terms": business_terms or [],
    }
    if semantic_type is not None:
        column["semantic_type"] = semantic_type
    return column


if __name__ == "__main__":
    unittest.main()
