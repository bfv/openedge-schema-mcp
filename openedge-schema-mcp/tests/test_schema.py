from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from openedge_schema_mcp.schema import SchemaCatalog


REPOSITORY_ROOT = Path(__file__).parents[2]
PROJECT_FILE = REPOSITORY_ROOT / "examples" / "openedge-project.json"


class SchemaCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = SchemaCatalog(PROJECT_FILE)

    def test_lists_configured_database_without_connection_string(self) -> None:
        databases = self.catalog.databases()

        self.assertEqual(["sports2020"], [database["name"] for database in databases])
        self.assertNotIn("connect", databases[0])

    def test_parses_customer_fields_and_primary_index(self) -> None:
        customer = self.catalog.schema("sports2020").table("Customer")

        self.assertEqual("integer", next(field.data_type for field in customer.fields if field.name == "CustNum"))
        self.assertEqual(["CustNum"], next(index.fields for index in customer.indexes if index.primary))

    def test_loads_configured_customer_relationship(self) -> None:
        relationships = self.catalog.relationships("sports2020", "Order")

        self.assertIn(
            {
                "from": {"database": "sports2020", "table": "Order", "fields": ["CustNum"]},
                "to": {"database": "sports2020", "table": "Customer", "fields": ["CustNum"]},
                "cardinality": "many-to-one",
                "source": "configured",
            },
            relationships,
        )

    def test_suggests_relationship_from_matching_unique_field(self) -> None:
        suggestions = self.catalog.suggested_relationships("sports2020", "Order")

        self.assertTrue(
            any(suggestion["to"]["table"] == "Customer" for suggestion in suggestions)
        )

    def test_loads_and_navigates_cross_database_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_directory = Path(directory)
            project_file = project_directory / "openedge-project.json"
            project_file.write_text(
                json.dumps(
                    {
                        "dbConnections": [
                            {"name": "orders", "schemaFile": str(PROJECT_FILE.parent / "sports2020.df")},
                            {"name": "crm", "schemaFile": str(PROJECT_FILE.parent / "sports2020.df")},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            relations_directory = project_directory / "schema-relations"
            relations_directory.mkdir()
            (relations_directory / "orders.json").write_text(
                json.dumps(
                    {
                        "database": "orders",
                        "relationships": [
                            {
                                "from": {"table": "Order", "fields": ["CustNum"]},
                                "to": {"database": "crm", "table": "Customer", "fields": ["CustNum"]},
                                "cardinality": "many-to-one",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            catalog = SchemaCatalog(project_file)

            incoming = catalog.relationships("crm", "Customer", "incoming")
            path = catalog.relationship_path("orders", "Order", "crm", "Customer")

        self.assertEqual("orders", incoming[0]["from"]["database"])
        self.assertEqual("crm", incoming[0]["to"]["database"])
        self.assertEqual(incoming, path)

    def test_uses_configured_relationship_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_directory = Path(directory)
            project_file = project_directory / "openedge-project.json"
            project_file.write_text(
                json.dumps(
                    {
                        "schemaRelationsDirectory": "metadata/relations",
                        "dbConnections": [
                            {"name": "sports2020", "schemaFile": str(PROJECT_FILE.parent / "sports2020.df")}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            relations_directory = project_directory / "metadata" / "relations"
            relations_directory.mkdir(parents=True)
            (relations_directory / "sports2020.json").write_text(
                json.dumps(
                    {
                        "database": "sports2020",
                        "relationships": [
                            {
                                "from": {"table": "Order", "fields": ["CustNum"]},
                                "to": {"table": "Customer", "fields": ["CustNum"]},
                                "cardinality": "many-to-one",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            relationships = SchemaCatalog(project_file).relationships("sports2020")

        self.assertEqual(1, len(relationships))

    def test_environment_relationship_directory_overrides_project_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_directory = Path(directory)
            project_file = project_directory / "openedge-project.json"
            project_file.write_text(
                json.dumps(
                    {
                        "schemaRelationsDirectory": "project-relations",
                        "dbConnections": [
                            {"name": "sports2020", "schemaFile": str(PROJECT_FILE.parent / "sports2020.df")}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            override_directory = project_directory / "override-relations"
            override_directory.mkdir()
            (override_directory / "sports2020.json").write_text(
                json.dumps(
                    {
                        "database": "sports2020",
                        "relationships": [
                            {
                                "from": {"table": "Order", "fields": ["CustNum"]},
                                "to": {"table": "Customer", "fields": ["CustNum"]},
                                "cardinality": "many-to-one",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"OPENEDGE_SCHEMA_RELATIONS_DIR": str(override_directory)}):
                relationships = SchemaCatalog(project_file).relationships("sports2020")

        self.assertEqual(1, len(relationships))

    def test_adds_relationship_to_catalog_and_avoids_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_directory = Path(directory)
            project_file = project_directory / "openedge-project.json"
            project_file.write_text(
                json.dumps(
                    {
                        "dbConnections": [
                            {"name": "sports2020", "schemaFile": str(PROJECT_FILE.parent / "sports2020.df")}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalog = SchemaCatalog(project_file)

            created = catalog.add_relationship(
                "sports2020", "OrderLine", ["OrderNum"], "Order", ["OrderNum"]
            )
            duplicate = catalog.add_relationship(
                "sports2020", "OrderLine", ["OrderNum"], "Order", ["OrderNum"]
            )

            relations_file = project_directory / "schema-relations" / "sports2020.json"
            document = json.loads(relations_file.read_text(encoding="utf-8"))

        self.assertTrue(created["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(1, len(document["relationships"]))
        self.assertEqual("OrderLine", document["relationships"][0]["from"]["table"])
