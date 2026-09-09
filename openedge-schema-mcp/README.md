# OpenEdge Schema MCP

A read-only stdio MCP server that reads the `dbConnections` entries in an OpenEdge `openedge-project.json` and parses their `schemaFile` `.df` exports. It never connects to a database and never exposes a database connection string.

## Tools

- `list_databases`
- `list_tables`
- `describe_table`
- `find_field`
- `list_indexes`
- `list_sequences`
- `find_relationships` (derived from `CAN-FIND` validation expressions)
- `search_schema`

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
uv run --directory tools/openedge-schema-mcp openedge-schema-mcp
```

The server finds `openedge-project.json` from the current directory. Set `OPENEDGE_PROJECT_FILE` to use another project file.

## Configure VS Code

Merge [mcp.json.example](mcp.json.example) into the local `.vscode/mcp.json`. That file is intentionally ignored because it can contain workstation-specific MCP credentials.

Run the tests with:

```sh
uv run --directory tools/openedge-schema-mcp --extra dev pytest
```