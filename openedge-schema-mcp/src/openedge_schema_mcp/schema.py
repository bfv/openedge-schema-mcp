"""Parse OpenEdge data-definition exports into a queryable schema model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import re


@dataclass
class Field:
    name: str
    table: str
    data_type: str
    format: str | None = None
    initial: str | None = None
    label: str | None = None
    help_text: str | None = None
    validation_expression: str | None = None
    validation_message: str | None = None
    mandatory: bool = False


@dataclass
class Index:
    name: str
    table: str
    fields: list[str] = field(default_factory=list)
    primary: bool = False
    unique: bool = False


@dataclass
class Table:
    name: str
    description: str | None = None
    dump_name: str | None = None
    triggers: list[str] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)


@dataclass
class Sequence:
    name: str
    initial: str | None = None
    increment: str | None = None
    minimum: str | None = None
    cycle_on_limit: bool = False


@dataclass
class DatabaseSchema:
    name: str
    schema_file: Path
    tables: dict[str, Table] = field(default_factory=dict)
    sequences: list[Sequence] = field(default_factory=list)

    def table(self, table_name: str) -> Table:
        for name, table in self.tables.items():
            if name.casefold() == table_name.casefold():
                return table
        raise ValueError(f"Table '{table_name}' was not found in database '{self.name}'.")


class SchemaCatalog:
    """Loads project database definitions and their exported schemas."""

    def __init__(self, project_file: Path | str | None = None) -> None:
        self.project_file = Path(project_file or "openedge-project.json").resolve()
        self._schemas: dict[str, DatabaseSchema] = {}

    def databases(self) -> list[dict[str, object]]:
        project = self._project()
        return [
            {
                "name": connection["name"],
                "schema_file": str(self._schema_path(connection)),
                "aliases": connection.get("aliases", []),
            }
            for connection in project.get("dbConnections", [])
        ]

    def schema(self, database_name: str) -> DatabaseSchema:
        key = database_name.casefold()
        if key not in self._schemas:
            connection = self._connection(database_name)
            self._schemas[key] = parse_df(
                database_name=connection["name"], schema_file=self._schema_path(connection)
            )
        return self._schemas[key]

    def _project(self) -> dict[str, object]:
        try:
            return json.loads(self.project_file.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ValueError(f"OpenEdge project file was not found: {self.project_file}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"OpenEdge project file is not valid JSON: {self.project_file}") from error

    def _connection(self, database_name: str) -> dict[str, object]:
        for connection in self._project().get("dbConnections", []):
            if connection["name"].casefold() == database_name.casefold():
                return connection
        raise ValueError(f"Database '{database_name}' is not configured in {self.project_file.name}.")

    def _schema_path(self, connection: dict[str, object]) -> Path:
        schema_file = connection.get("schemaFile")
        if not schema_file:
            raise ValueError(f"Database '{connection['name']}' has no schemaFile configured.")
        return (self.project_file.parent / str(schema_file)).resolve()


def parse_df(database_name: str, schema_file: Path | str) -> DatabaseSchema:
    """Parse the schema objects represented by OpenEdge ADD statements."""
    schema_path = Path(schema_file)
    try:
        blocks = re.split(r"\n\s*\n", schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Schema file was not found: {schema_path}") from error

    schema = DatabaseSchema(name=database_name, schema_file=schema_path)
    for block in blocks:
        if match := re.search(r'^ADD TABLE "([^"]+)"', block, re.MULTILINE):
            table = Table(
                name=match.group(1),
                description=_quoted_property(block, "DESCRIPTION"),
                dump_name=_quoted_property(block, "DUMP-NAME"),
                triggers=re.findall(r'TABLE-TRIGGER "[^"]+"[^\n]*PROCEDURE "([^"]+)"', block),
            )
            schema.tables[table.name] = table
        elif match := re.search(r'^ADD FIELD "([^"]+)" OF "([^"]+)" AS (\w+)', block, re.MULTILINE):
            field_definition = Field(
                name=match.group(1),
                table=match.group(2),
                data_type=match.group(3),
                format=_quoted_property(block, "FORMAT"),
                initial=_quoted_property(block, "INITIAL"),
                label=_quoted_property(block, "LABEL"),
                help_text=_quoted_property(block, "HELP"),
                validation_expression=_quoted_property(block, "VALEXP"),
                validation_message=_quoted_property(block, "VALMSG"),
                mandatory=bool(re.search(r'\bMANDATORY\b', block)),
            )
            if field_definition.table in schema.tables:
                schema.tables[field_definition.table].fields.append(field_definition)
        elif match := re.search(r'^ADD INDEX "([^"]+)" ON "([^"]+)"', block, re.MULTILINE):
            index = Index(
                name=match.group(1),
                table=match.group(2),
                fields=re.findall(r'INDEX-FIELD "([^"]+)"', block),
                primary=bool(re.search(r'\bPRIMARY\b', block)),
                unique=bool(re.search(r'\bUNIQUE\b', block)),
            )
            if index.table in schema.tables:
                schema.tables[index.table].indexes.append(index)
        elif match := re.search(r'^ADD SEQUENCE "([^"]+)"', block, re.MULTILINE):
            schema.sequences.append(
                Sequence(
                    name=match.group(1),
                    initial=_value_property(block, "INITIAL"),
                    increment=_value_property(block, "INCREMENT"),
                    minimum=_value_property(block, "MIN-VAL"),
                    cycle_on_limit=bool(re.search(r'CYCLE-ON-LIMIT yes', block)),
                )
            )
    return schema


def table_details(table: Table) -> dict[str, object]:
    return asdict(table)


def inferred_relationships(schema: DatabaseSchema, table_name: str | None = None) -> list[dict[str, str]]:
    tables = [schema.table(table_name)] if table_name else schema.tables.values()
    relationships: list[dict[str, str]] = []
    pattern = re.compile(r'CAN-FIND\s*\(\s*(?:FIRST\s+)?([A-Za-z][A-Za-z0-9_-]*)\s+(?:OF|WHERE)', re.IGNORECASE)
    for table in tables:
        for field_definition in table.fields:
            expression = field_definition.validation_expression or ""
            for target_table in pattern.findall(expression):
                relationships.append(
                    {
                        "source_table": table.name,
                        "source_field": field_definition.name,
                        "target_table": target_table,
                        "source": "inferred from VALEXP CAN-FIND",
                    }
                )
    return relationships


def _quoted_property(block: str, property_name: str) -> str | None:
    match = re.search(rf'\b{re.escape(property_name)} "(.*?)"', block, re.DOTALL)
    return re.sub(r'\s+', ' ', match.group(1)).strip() if match else None


def _value_property(block: str, property_name: str) -> str | None:
    match = re.search(rf'\b{re.escape(property_name)}\s+([^\s]+)', block)
    return match.group(1) if match else None
