from pathlib import Path
import unittest

from openedge_schema_mcp.schema import SchemaCatalog, inferred_relationships


PROJECT_ROOT = Path(__file__).parents[3]
PROJECT_FILE = PROJECT_ROOT / "openedge-project.json"


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

    def test_infers_customer_relationship_from_validation_expression(self) -> None:
        relationships = inferred_relationships(self.catalog.schema("sports2020"), "Order")

        self.assertIn(
            {
                "source_table": "Order",
                "source_field": "CustNum",
                "target_table": "customer",
                "source": "inferred from VALEXP CAN-FIND",
            },
            relationships,
        )
