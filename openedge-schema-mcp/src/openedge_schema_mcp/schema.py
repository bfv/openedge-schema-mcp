"""Parse OpenEdge data-definition exports into a queryable schema model."""

from __future__ import annotations

import codecs
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import re
import tempfile


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


@dataclass(frozen=True)
class RelationshipEndpoint:
    database: str
    table: str
    fields: list[str]


@dataclass(frozen=True)
class Relationship:
    from_endpoint: RelationshipEndpoint
    to_endpoint: RelationshipEndpoint
    cardinality: str
    name: str | None = None
    description: str | None = None


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

    def relationships(
        self, database_name: str, table_name: str | None = None, direction: str = "both"
    ) -> list[dict[str, object]]:
        if direction not in {"both", "outgoing", "incoming"}:
            raise ValueError("direction must be 'both', 'outgoing', or 'incoming'.")

        database = self.schema(database_name).name
        relationships = self._load_relationships()
        return [
            relationship_details(relationship)
            for relationship in relationships
            if _relationship_matches(relationship, database, table_name, direction)
        ]

    def related_tables(self, database_name: str, table_name: str, depth: int = 1) -> list[dict[str, object]]:
        if depth < 1:
            raise ValueError("depth must be at least 1.")

        source_database = self.schema(database_name).name
        source_table = self.schema(source_database).table(table_name).name
        frontier = {(source_database.casefold(), source_table.casefold())}
        visited = set(frontier)
        related: list[dict[str, object]] = []

        for current_depth in range(1, depth + 1):
            next_frontier: set[tuple[str, str]] = set()
            for relationship in self._load_relationships():
                endpoints = (relationship.from_endpoint, relationship.to_endpoint)
                for endpoint, other_endpoint in (endpoints, endpoints[::-1]):
                    if (endpoint.database.casefold(), endpoint.table.casefold()) not in frontier:
                        continue
                    other_key = (other_endpoint.database.casefold(), other_endpoint.table.casefold())
                    if other_key in visited:
                        continue
                    visited.add(other_key)
                    next_frontier.add(other_key)
                    related.append(
                        {
                            "database": other_endpoint.database,
                            "table": other_endpoint.table,
                            "depth": current_depth,
                            "relationship": relationship_details(relationship),
                        }
                    )
            frontier = next_frontier
            if not frontier:
                break
        return related

    def relationship_path(
        self,
        from_database: str,
        from_table: str,
        to_database: str,
        to_table: str,
        max_depth: int = 4,
    ) -> list[dict[str, object]]:
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1.")

        start = self._table_key(from_database, from_table)
        target = self._table_key(to_database, to_table)
        if start == target:
            return []

        paths: list[tuple[tuple[str, str], list[Relationship]]] = [(start, [])]
        visited = {start}
        for _ in range(max_depth):
            next_paths: list[tuple[tuple[str, str], list[Relationship]]] = []
            for endpoint, path in paths:
                for relationship in self._load_relationships():
                    for current, other in (
                        (relationship.from_endpoint, relationship.to_endpoint),
                        (relationship.to_endpoint, relationship.from_endpoint),
                    ):
                        other_key = (other.database.casefold(), other.table.casefold())
                        if (current.database.casefold(), current.table.casefold()) != endpoint or other_key in visited:
                            continue
                        next_path = [*path, relationship]
                        if other_key == target:
                            return [relationship_details(item) for item in next_path]
                        visited.add(other_key)
                        next_paths.append((other_key, next_path))
            paths = next_paths
        return []

    def suggested_relationships(self, database_name: str, table_name: str | None = None) -> list[dict[str, object]]:
        source_schema = self.schema(database_name)
        source_tables = [source_schema.table(table_name)] if table_name else source_schema.tables.values()
        suggestions: list[dict[str, object]] = []
        for source_table in source_tables:
            for source_field in source_table.fields:
                for target_table in source_schema.tables.values():
                    if target_table.name.casefold() == source_table.name.casefold():
                        continue
                    target_field = next(
                        (field for field in target_table.fields if field.name.casefold() == source_field.name.casefold()),
                        None,
                    )
                    if target_field is None or target_field.data_type.casefold() != source_field.data_type.casefold():
                        continue
                    if not any(
                        index.unique and [field.casefold() for field in index.fields] == [target_field.name.casefold()]
                        for index in target_table.indexes
                    ):
                        continue
                    suggestions.append(
                        {
                            "from": {"database": source_schema.name, "table": source_table.name, "fields": [source_field.name]},
                            "to": {"database": source_schema.name, "table": target_table.name, "fields": [target_field.name]},
                            "cardinality": "many-to-one",
                            "confidence": "high",
                            "evidence": ["matching field name and data type", "target field is a single-field unique index"],
                        }
                    )
        return suggestions

    def add_relationship(
        self,
        database_name: str,
        from_table: str,
        from_fields: list[str],
        to_table: str,
        to_fields: list[str],
        to_database: str | None = None,
        cardinality: str = "many-to-one",
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, object]:
        database = self.schema(database_name).name
        target_database = self.schema(to_database or database).name
        entry: dict[str, object] = {
            "from": {"table": from_table, "fields": from_fields},
            "to": {"table": to_table, "fields": to_fields},
            "cardinality": cardinality,
        }
        if target_database.casefold() != database.casefold():
            entry["to"]["database"] = target_database
        if name is not None:
            entry["name"] = name
        if description is not None:
            entry["description"] = description

        relations_file = self._relationships_directory() / f"{database}.json"
        relationship = self._parse_relationship(entry, database, relations_file)
        for existing_relationship in self._load_relationships():
            if _same_relationship(existing_relationship, relationship):
                return {"created": False, "relationship": relationship_details(existing_relationship)}

        document = self._relationship_document(relations_file, database)
        document["relationships"].append(entry)
        self._write_relationship_document(relations_file, document)
        return {"created": True, "relationship": relationship_details(relationship)}

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

    def _table_key(self, database_name: str, table_name: str) -> tuple[str, str]:
        database = self.schema(database_name).name
        table = self.schema(database).table(table_name).name
        return (database.casefold(), table.casefold())

    def _load_relationships(self) -> list[Relationship]:
        relationships: list[Relationship] = []
        relations_directory = self._relationships_directory()
        if not relations_directory.is_dir():
            return relationships
        for relations_file in sorted(relations_directory.glob("*.json")):
            try:
                document = json.loads(relations_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError(f"Relationship file is not valid JSON: {relations_file}") from error
            default_database = document.get("database")
            if not isinstance(default_database, str):
                raise ValueError(f"Relationship file has no database: {relations_file}")
            entries = document.get("relationships")
            if not isinstance(entries, list):
                raise ValueError(f"Relationship file has no relationships array: {relations_file}")
            for entry in entries:
                relationships.append(self._parse_relationship(entry, default_database, relations_file))
        return relationships

    def _relationships_directory(self) -> Path:
        configured_directory = os.environ.get("OPENEDGE_SCHEMA_RELATIONS_DIR")
        if configured_directory is None:
            configured_directory = self._project().get("schemaRelationsDirectory", "schema-relations")
        if not isinstance(configured_directory, str):
            raise ValueError("schemaRelationsDirectory must be a string.")
        return (self.project_file.parent / configured_directory).resolve()

    def _relationship_document(self, relations_file: Path, database_name: str) -> dict[str, object]:
        if not relations_file.exists():
            return {"database": database_name, "relationships": []}
        try:
            document = json.loads(relations_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Relationship file is not valid JSON: {relations_file}") from error
        if not isinstance(document, dict) or not isinstance(document.get("relationships"), list):
            raise ValueError(f"Relationship file has no relationships array: {relations_file}")
        configured_database = document.get("database")
        if not isinstance(configured_database, str) or configured_database.casefold() != database_name.casefold():
            raise ValueError(f"Relationship file database does not match '{database_name}': {relations_file}")
        return document

    def _write_relationship_document(self, relations_file: Path, document: dict[str, object]) -> None:
        relations_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=relations_file.parent,
            prefix=f".{relations_file.name}.", suffix=".tmp", delete=False,
        ) as temporary_file:
            json.dump(document, temporary_file, indent=2)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(relations_file)

    def _parse_relationship(
        self, entry: object, default_database: str, relations_file: Path
    ) -> Relationship:
        if not isinstance(entry, dict):
            raise ValueError(f"Relationship must be an object in {relations_file}")
        cardinality = entry.get("cardinality")
        if cardinality not in {"many-to-one", "one-to-one", "many-to-many"}:
            raise ValueError(f"Relationship has an invalid cardinality in {relations_file}")
        relationship = Relationship(
            from_endpoint=self._parse_endpoint(entry.get("from"), default_database, relations_file),
            to_endpoint=self._parse_endpoint(entry.get("to"), default_database, relations_file),
            cardinality=cardinality,
            name=entry.get("name"),
            description=entry.get("description"),
        )
        if len(relationship.from_endpoint.fields) != len(relationship.to_endpoint.fields):
            raise ValueError(f"Relationship field counts do not match in {relations_file}")
        return relationship

    def _parse_endpoint(self, endpoint: object, default_database: str, relations_file: Path) -> RelationshipEndpoint:
        if not isinstance(endpoint, dict):
            raise ValueError(f"Relationship endpoint must be an object in {relations_file}")
        database_name = endpoint.get("database", default_database)
        table_name = endpoint.get("table")
        field_names = endpoint.get("fields")
        if not isinstance(database_name, str) or not isinstance(table_name, str) or not (
            isinstance(field_names, list) and all(isinstance(field, str) for field in field_names) and field_names
        ):
            raise ValueError(f"Relationship endpoint is invalid in {relations_file}")
        table = self.schema(database_name).table(table_name)
        actual_fields = {field.name.casefold(): field.name for field in table.fields}
        try:
            fields = [actual_fields[field.casefold()] for field in field_names]
        except KeyError as error:
            raise ValueError(f"Relationship field was not found in {table.name} ({relations_file})") from error
        return RelationshipEndpoint(database=self.schema(database_name).name, table=table.name, fields=fields)


def parse_df(database_name: str, schema_file: Path | str) -> DatabaseSchema:
    """Parse the schema objects represented by OpenEdge ADD statements."""
    schema_path = Path(schema_file)
    try:
        blocks = re.split(r"\r?\n\s*\r?\n", _read_df_text(schema_path))
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


def relationship_details(relationship: Relationship) -> dict[str, object]:
    details: dict[str, object] = {
        "from": asdict(relationship.from_endpoint),
        "to": asdict(relationship.to_endpoint),
        "cardinality": relationship.cardinality,
        "source": "configured",
    }
    if relationship.name is not None:
        details["name"] = relationship.name
    if relationship.description is not None:
        details["description"] = relationship.description
    return details


def _relationship_matches(
    relationship: Relationship, database_name: str, table_name: str | None, direction: str
) -> bool:
    def matches(endpoint: RelationshipEndpoint) -> bool:
        return endpoint.database.casefold() == database_name.casefold() and (
            table_name is None or endpoint.table.casefold() == table_name.casefold()
        )

    return (direction in {"both", "outgoing"} and matches(relationship.from_endpoint)) or (
        direction in {"both", "incoming"} and matches(relationship.to_endpoint)
    )


def _same_relationship(first: Relationship, second: Relationship) -> bool:
    return (
        first.from_endpoint == second.from_endpoint
        and first.to_endpoint == second.to_endpoint
        and first.cardinality == second.cardinality
    )


def _quoted_property(block: str, property_name: str) -> str | None:
    match = re.search(rf'\b{re.escape(property_name)} "(.*?)"', block, re.DOTALL)
    return re.sub(r'\s+', ' ', match.group(1)).strip() if match else None


def _value_property(block: str, property_name: str) -> str | None:
    match = re.search(rf'\b{re.escape(property_name)}\s+([^\s]+)', block)
    return match.group(1) if match else None


def _read_df_text(schema_path: Path) -> str:
    contents = schema_path.read_bytes()
    try:
        source_encoding = _detect_df_encoding(contents) or "utf-8"
    except UnicodeDecodeError as error:
        raise ValueError(f"Schema file contains a non-ASCII cpstream value: {schema_path}") from error
    encoding = _normalize_df_encoding(source_encoding)
    try:
        return contents.decode(encoding)
    except LookupError as error:
        raise ValueError(
            f"Schema file uses an unsupported cpstream '{source_encoding}' (normalized as '{encoding}'): {schema_path}"
        ) from error
    except UnicodeDecodeError as error:
        raise ValueError(
            f"Schema file could not be decoded with cpstream '{source_encoding}' (normalized as '{encoding}'): {schema_path}"
        ) from error


def _detect_df_encoding(contents: bytes) -> str | None:
    matches = list(
        re.finditer(rb'(?i)cpstream\s*=\s*(?:"([^"\r\n]+)"|([^\s"\r\n]+))', contents)
    )
    if not matches:
        return None
    value = matches[-1].group(1) or matches[-1].group(2)
    return value.decode("ascii").strip()


def _normalize_df_encoding(encoding: str) -> str:
    normalized = encoding.strip()
    if not normalized:
        return normalized
    try:
        codecs.lookup(normalized)
        return normalized
    except LookupError:
        pass

    compact = re.sub(r"[\s_-]+", "", normalized).casefold()
    if compact == "utf8":
        return "utf-8"
    if match := re.fullmatch(r"iso8859(\d+)", compact):
        return f"iso-8859-{match.group(1)}"
    if match := re.fullmatch(r"(?:windows|cp)(\d+)", compact):
        return f"cp{match.group(1)}"
    return normalized
