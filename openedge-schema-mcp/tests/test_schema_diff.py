import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from openedge_schema_mcp.schema_diff import compare_schema_versions


BASE_SCHEMA = '''ADD TABLE "Customer"
  DESCRIPTION "Customers"

ADD TABLE "LegacyTable"

ADD FIELD "CustNum" OF "Customer" AS integer
  INITIAL "1500"
  MANDATORY

ADD FIELD "Address" OF "Customer" AS character
  FORMAT "x(30)"

ADD FIELD "Name" OF "Customer" AS character
  FORMAT "x(30)"

ADD FIELD "Obsolete" OF "Customer" AS integer

ADD INDEX "CustomerKey" ON "Customer"
  UNIQUE
  PRIMARY
  INDEX-FIELD "CustNum"

ADD SEQUENCE "NextCustomer"
  INITIAL 1
  INCREMENT 1

ADD SEQUENCE "NextLegacy"
  INITIAL 1
  INCREMENT 1
'''

TARGET_SCHEMA = '''ADD TABLE "Customer"
  DESCRIPTION "Customers"

ADD TABLE "NewTable"

ADD FIELD "CustNum" OF "Customer" AS decimal
  INITIAL "2000"
  MANDATORY

ADD FIELD "Address" OF "Customer" AS character
  FORMAT "x(20)"

ADD FIELD "PreferredLanguage" OF "Customer" AS character
  FORMAT "x(20)"

ADD FIELD "Name" OF "Customer" AS character
  FORMAT "x(30)"
  INITIAL ""

ADD INDEX "CustomerKey" ON "Customer"
  UNIQUE
  PRIMARY
  INDEX-FIELD "CustNum"

ADD INDEX "CustomerName" ON "Customer"
  INDEX-FIELD "Name"

ADD INDEX "CustomerEmail" ON "Customer"
  UNIQUE
  INDEX-FIELD "Name"

ADD SEQUENCE "NextCustomer"
  INITIAL 1
  INCREMENT 1

ADD SEQUENCE "NextOrder"
  INITIAL 1
  INCREMENT 1
'''


class SchemaVersionDiffTests(unittest.TestCase):
    def test_compares_files_and_classifies_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_path = Path(directory) / "before.df"
            target_path = Path(directory) / "after.df"
            base_path.write_text(BASE_SCHEMA, encoding="utf-8")
            target_path.write_text(TARGET_SCHEMA, encoding="utf-8")

            result = compare_schema_versions(str(base_path), str(target_path))

        self.assertEqual("files", result["source"]["mode"])
        self.assertEqual("after", result["database"])
        customer = result["tables"]["modified"][0]
        changed_field = next(field for field in customer["fields"]["modified"] if field["name"] == "CustNum")
        self.assertEqual(
            {"from": "integer", "to": "decimal"}, changed_field["changes"]["data_type"]
        )
        self.assertEqual("breaking", changed_field["classification"])
        self.assertEqual(["PreferredLanguage"], customer["fields"]["added"])
        self.assertEqual(["Obsolete"], customer["fields"]["removed"])
        self.assertEqual("breaking", customer["fields"]["removed_classification"])
        self.assertEqual(
            "potential_data_migration",
            next(field for field in customer["fields"]["modified"] if field["name"] == "Address")[
                "classification"
            ],
        )
        self.assertEqual(
            "potential_data_migration",
            next(field for field in customer["fields"]["modified"] if field["name"] == "Name")[
                "classification"
            ],
        )
        self.assertEqual(
            ["CustomerEmail", "CustomerName"], customer["indexes"]["added"]
        )
        self.assertEqual(["CustomerEmail"], customer["indexes"]["primary_or_unique"]["added"])
        self.assertEqual(["LegacyTable"], result["tables"]["removed"])
        self.assertEqual(["NewTable"], result["tables"]["added"])
        self.assertEqual(["NextOrder"], result["sequences"]["added"])
        self.assertEqual(["NextLegacy"], result["sequences"]["removed"])
        self.assertEqual(4, result["summary"]["additive_changes"])
        self.assertEqual(2, result["summary"]["potential_data_migrations"])
        self.assertEqual(5, result["summary"]["breaking_changes"])

    def test_rejects_incomplete_and_mixed_modes(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires both base_schema_file"):
            compare_schema_versions(base_schema_file="before.df")
        with self.assertRaisesRegex(ValueError, "exactly one comparison mode"):
            compare_schema_versions(
                base_schema_file="before.df",
                target_schema_file="after.df",
                base_ref="main",
                target_ref="feature",
                schema_file="schema.df",
            )
        with self.assertRaisesRegex(ValueError, "requires base_ref, target_ref, and schema_file"):
            compare_schema_versions(base_ref="main", target_ref="feature")

    def test_compares_git_refs_without_changing_working_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Schema Test"], cwd=root, check=True)
            schema_path = root / "db" / "schema.df"
            schema_path.parent.mkdir()
            schema_path.write_text(BASE_SCHEMA, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            schema_path.write_text(TARGET_SCHEMA, encoding="utf-8")
            subprocess.run(["git", "commit", "-qam", "target"], cwd=root, check=True)
            target_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            before_status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
            ).stdout
            original_directory = Path.cwd()
            try:
                os.chdir(root)
                result = compare_schema_versions(
                    base_ref=base_ref, target_ref=target_ref, schema_file="db/schema.df"
                )
            finally:
                os.chdir(original_directory)
            after_status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
            ).stdout

        self.assertEqual("git_refs", result["source"]["mode"])
        self.assertEqual(f"{base_ref}:db/schema.df", result["source"]["base"])
        self.assertEqual(before_status, after_status)

    def test_reports_missing_git_schema_with_ref_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "schema.df").write_text(BASE_SCHEMA, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Schema Test"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            original_directory = Path.cwd()
            try:
                os.chdir(root)
                with self.assertRaisesRegex(ValueError, "missing-ref:schema.df"):
                    compare_schema_versions(
                        base_ref="missing-ref",
                        target_ref="HEAD",
                        schema_file="schema.df",
                    )
            finally:
                os.chdir(original_directory)

    def test_rejects_non_workspace_relative_git_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspace-relative .df path"):
            compare_schema_versions(
                base_ref="main",
                target_ref="feature",
                schema_file="../schema.df",
            )


if __name__ == "__main__":
    unittest.main()
