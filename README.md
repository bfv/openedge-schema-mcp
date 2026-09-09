# OpenEdge Schema MCP

An MCP server that lets AI assistants explore OpenEdge database schemas and maintain a relationship catalog. It reads `.df` exports referenced by `openedge-project.json`; it never connects to a database or returns connection strings.

## How a project uses it

The server is a separate Python process. It is not added to the OpenEdge `PROPATH`, and it does not connect to the database. VS Code starts the server and passes it the path to the OpenEdge project file. The server then reads the schema exports and relationship catalog from that project.

The recommended setup runs a version-pinned release directly from GitHub. A local checkout is only needed when developing or testing a server change.

```text
my-openedge-project/
├── .vscode/
│   └── mcp.json                         # Starts the MCP server
├── openedge-project.json                # Existing OpenEdge project configuration
├── sports2020.df                        # Schema export referenced by schemaFile
├── schema-relations/
│   └── sports2020.json                  # Relationship catalog
```

### 1. Configure schema file locations

Export a `.df` file for each database and set its location in the database's `schemaFile` property. There is no global schema-directory setting: every database can have its own schema file location.

```json
{
  "dbConnections": [
    {
      "name": "sports2020",
      "connect": "-db sports2020 -S 10000 -H db",
      "schemaFile": "./sports2020.df",
      "aliases": []
    }
  ]
}
```

`schemaFile` is resolved relative to `openedge-project.json`. It may also be an absolute path when the exports are stored outside the project directory. The connection string is only needed by your OpenEdge project; the MCP server neither uses nor returns it.

`OPENEDGE_PROJECT_FILE` in `.vscode/mcp.json` selects the `openedge-project.json` file the MCP server reads. The `schemaFile` values inside that selected project file determine the schema locations.

### 2. Configure relationships

OpenEdge schemas do not contain formal foreign keys. By default, store reviewed relationships in `schema-relations/<database>.json`:

```json
{
  "database": "sports2020",
  "relationships": [
    {
      "from": { "table": "Order", "fields": ["CustNum"] },
      "to": { "table": "Customer", "fields": ["CustNum"] },
      "cardinality": "many-to-one",
      "name": "order_customer"
    }
  ]
}
```

`from` is the referencing table and `to` is the target or parent table. Both endpoints inherit the document-level database, but may specify their own `database` for cross-database relationships:

```json
{
  "database": "orders",
  "relationships": [
    {
      "from": { "table": "Order", "fields": ["CustNum"] },
      "to": {
        "database": "crm",
        "table": "Customer",
        "fields": ["CustNum"]
      },
      "cardinality": "many-to-one"
    }
  ]
}
```

The server validates every referenced database, table, and field while loading. Use `suggest_relationships` to find local candidates, then review them before adding them to the catalog. `add_relationship` lets an MCP client create a relationship from a prompt; it validates the endpoints and does not add an identical relationship twice.

Set `schemaRelationsDirectory` in `openedge-project.json` to use another directory. Relative paths are resolved from the project file:

```json
{
  "schemaRelationsDirectory": "./metadata/schema-relations",
  "dbConnections": []
}
```

`OPENEDGE_SCHEMA_RELATIONS_DIR` overrides this setting, which is useful when each workstation needs a different relationship catalog.

### 3. Configure VS Code from GitHub

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and create `.vscode/mcp.json` in the project root:

```json
{
  "servers": {
    "openedge-schema": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/bfv/openedge-schema-mcp.git@v0.2.0#subdirectory=openedge-schema-mcp",
        "openedge-schema-mcp"
      ],
      "env": {
        "OPENEDGE_PROJECT_FILE": "${workspaceFolder}/openedge-project.json",
        "OPENEDGE_SCHEMA_RELATIONS_DIR": "${workspaceFolder}/schema-relations"
      }
    }
  }
}
```

`OPENEDGE_SCHEMA_RELATIONS_DIR` sets the directory where `add_relationship` creates and updates `<database>.json` files. It overrides `schemaRelationsDirectory` in `openedge-project.json`; remove this environment variable when the project-file setting should control the catalog location. `uvx` downloads and caches the release from the `v0.2.0` Git tag. The tag pin keeps every project on a known server version. Restart the MCP server from the VS Code MCP view after saving this file.

To upgrade, change `@v0.2.0` to the required release tag, such as `@v0.3.0`, then restart the MCP server. Do not point production projects at `main`, because that would allow unreviewed server changes to alter the project setup.

### Local checkout alternative

For server development, put the directory containing the server's `pyproject.toml` at `tools/openedge-schema-mcp` and replace the GitHub configuration with:

```json
{
  "servers": {
    "openedge-schema": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "${workspaceFolder}/tools/openedge-schema-mcp",
        "openedge-schema-mcp"
      ],
      "env": {
        "OPENEDGE_PROJECT_FILE": "${workspaceFolder}/openedge-project.json",
        "OPENEDGE_SCHEMA_RELATIONS_DIR": "${workspaceFolder}/schema-relations"
      }
    }
  }
}
```

### 4. Use the tools from a prompt

Once VS Code shows the server as running, an assistant can inspect the configured schema. For example:

```text
Describe the OrderLine table in sports2020.
What is the relationship path from OrderLine to Customer?
Create a many-to-one relationship from OrderLine.OrderNum to Order.OrderNum in sports2020.
```

The last prompt invokes `add_relationship`. It validates the named databases, tables, and fields, then writes the relationship to `schema-relations/sports2020.json` (or the configured override). Repeating the same request does not create a duplicate.

## Available tools

- `list_databases`, `list_tables`, `describe_table`
- `find_field`, `list_indexes`, `list_sequences`, `search_schema`
- `find_relationships`, with optional table and direction filtering
- `get_related_tables`, for direct or deeper relationships
- `find_relationship_path`, including paths across databases
- `suggest_relationships`, for relationship candidates to review
- `add_relationship`, to validate and add a relationship to the JSON catalog

## Developing the server

See [openedge-schema-mcp/README.md](openedge-schema-mcp/README.md) for installing, testing, and running the Python package locally.