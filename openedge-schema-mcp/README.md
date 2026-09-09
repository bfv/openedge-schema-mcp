# OpenEdge Schema MCP

An stdio MCP server that reads the `dbConnections` entries in an OpenEdge `openedge-project.json`, parses their `schemaFile` `.df` exports, and maintains a relationship catalog. It never connects to a database and never exposes a database connection string.

## Tools

- `list_databases`
- `list_tables`
- `describe_table`
- `find_field`
- `list_indexes`
- `list_sequences`
- `find_relationships` (from `schema-relations/<database>.json`)
- `get_related_tables`
- `find_relationship_path`
- `suggest_relationships` (candidates to review before configuring)
- `add_relationship` (validates and adds a relationship to the JSON catalog)
- `search_schema`

## Relationships

By default, add reviewed relationships to `schema-relations/<database>.json`, next to the project file. Set `schemaRelationsDirectory` in `openedge-project.json` to configure a different directory; relative paths are resolved from the project file. `OPENEDGE_SCHEMA_RELATIONS_DIR` takes precedence, so an MCP client can supply a workstation-specific directory. An endpoint inherits the document-level `database` unless it supplies its own `database`, which supports cross-database relationships.

```json
{
	"database": "sports2020",
	"relationships": [
		{
			"from": { "table": "Order", "fields": ["CustNum"] },
			"to": { "database": "crm", "table": "Customer", "fields": ["CustNum"] },
			"cardinality": "many-to-one",
			"name": "order_customer"
		}
	]
}
```

Each referenced database, table, and field is validated while loading. `suggest_relationships` only proposes local candidates whose field name and type match a single-field unique target index; it never changes this configuration.

## Development container

Install Docker Desktop and the VS Code **Dev Containers** extension. In VS Code, run **Dev Containers: Reopen in Container**. Python and `uv` then run only inside the container; they do not need to be installed on the host.

After the container has opened, run the tests from the integrated terminal:

```sh
cd openedge-schema-mcp
uv run --extra dev pytest
```

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
uv run --directory /path/to/openedge-schema-mcp openedge-schema-mcp
```

The server finds `openedge-project.json` from the current directory. Set `OPENEDGE_PROJECT_FILE` to use another project file.

## Configure VS Code

Merge [mcp.json.example](mcp.json.example) into the local `.vscode/mcp.json`. That file is intentionally ignored because it can contain workstation-specific MCP credentials.

Run the tests with:

```sh
uv run --directory /path/to/openedge-schema-mcp --extra dev pytest
```