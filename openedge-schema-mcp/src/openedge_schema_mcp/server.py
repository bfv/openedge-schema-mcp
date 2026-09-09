"""MCP tools for querying the schema configured by openedge-project.json."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .schema import SchemaCatalog, table_details

mcp = FastMCP("OpenEdge Schema")


def catalog() -> SchemaCatalog:
    return SchemaCatalog(Path(os.environ.get("OPENEDGE_PROJECT_FILE", "openedge-project.json")))


@mcp.tool()
def list_databases() -> list[dict[str, object]]:
    """List databases configured in openedge-project.json without exposing connection strings."""
    return catalog().databases()


@mcp.tool()
def list_tables(database: str, pattern: str | None = None) -> list[dict[str, str | None]]:
    """List tables and descriptions, optionally filtering by a case-insensitive name fragment."""
    schema = catalog().schema(database)
    needle = pattern.casefold() if pattern else ""
    return [
        {"name": table.name, "description": table.description}
        for table in schema.tables.values()
        if needle in table.name.casefold()
    ]


@mcp.tool()
def describe_table(database: str, table: str) -> dict[str, object]:
    """Return fields, indexes, and triggers for one table."""
    return table_details(catalog().schema(database).table(table))


@mcp.tool()
def find_field(database: str, field: str, table: str | None = None) -> list[dict[str, object]]:
    """Find fields by case-insensitive name, optionally within one table."""
    schema = catalog().schema(database)
    tables = [schema.table(table)] if table else schema.tables.values()
    needle = field.casefold()
    return [
        {
            "table": current_table.name,
            "field": field_definition.name,
            "data_type": field_definition.data_type,
            "label": field_definition.label,
            "validation_expression": field_definition.validation_expression,
        }
        for current_table in tables
        for field_definition in current_table.fields
        if needle in field_definition.name.casefold()
    ]


@mcp.tool()
def list_indexes(database: str, table: str) -> list[dict[str, object]]:
    """List indexes and ordered fields for a table."""
    return [index.__dict__ for index in catalog().schema(database).table(table).indexes]


@mcp.tool()
def list_sequences(database: str) -> list[dict[str, object]]:
    """List sequences defined in the database schema."""
    return [sequence.__dict__ for sequence in catalog().schema(database).sequences]


@mcp.tool()
def find_relationships(
    database: str, table: str | None = None, direction: str = "both"
) -> list[dict[str, object]]:
    """Find configured table relationships, optionally filtered by table and direction."""
    return catalog().relationships(database, table, direction)


@mcp.tool()
def get_related_tables(database: str, table: str, depth: int = 1) -> list[dict[str, object]]:
    """Return tables connected to one table by configured relationships."""
    return catalog().related_tables(database, table, depth)


@mcp.tool()
def find_relationship_path(
    from_database: str, from_table: str, to_database: str, to_table: str, max_depth: int = 4
) -> list[dict[str, object]]:
    """Find the shortest configured relationship path between two tables."""
    return catalog().relationship_path(from_database, from_table, to_database, to_table, max_depth)


@mcp.tool()
def suggest_relationships(database: str, table: str | None = None) -> list[dict[str, object]]:
    """Suggest local relationship candidates; review them before adding configuration."""
    return catalog().suggested_relationships(database, table)


@mcp.tool()
def add_relationship(
    database: str,
    from_table: str,
    from_fields: list[str],
    to_table: str,
    to_fields: list[str],
    to_database: str | None = None,
    cardinality: str = "many-to-one",
    name: str | None = None,
    description: str | None = None,
) -> dict[str, object]:
    """Validate and add a relationship to the configured JSON catalog."""
    return catalog().add_relationship(
        database,
        from_table,
        from_fields,
        to_table,
        to_fields,
        to_database,
        cardinality,
        name,
        description,
    )


@mcp.tool()
def search_schema(database: str, query: str) -> list[dict[str, str]]:
    """Search table names, field names, descriptions, labels, and help text."""
    needle = query.casefold()
    matches: list[dict[str, str]] = []
    for table in catalog().schema(database).tables.values():
        table_text = " ".join(filter(None, [table.name, table.description, table.dump_name])).casefold()
        if needle in table_text:
            matches.append({"kind": "table", "table": table.name, "name": table.name})
        for field_definition in table.fields:
            field_text = " ".join(
                filter(None, [field_definition.name, field_definition.label, field_definition.help_text])
            ).casefold()
            if needle in field_text:
                matches.append({"kind": "field", "table": table.name, "name": field_definition.name})
    return matches


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
