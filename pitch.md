# OpenEdge Schema MCP

## Management Summary (TL;DR)

OpenEdge Schema MCP gives AI assistants trusted, reviewable access to an OpenEdge application's schema without granting database access or exposing connection strings. By combining `.df` exports with a version-controlled relationship catalog, it replaces guesswork about tables, fields, and implicit joins with evidence. Teams can deliver safer ABL assistance, faster onboarding, and more informed schema-change reviews while keeping control of what the assistant is allowed to know.

## Give AI assistants the context to work safely with OpenEdge

OpenEdge applications often carry decades of valuable business logic, but their data model is difficult for a new developer, a modernization team, or an AI assistant to understand. A `.df` export describes tables, fields, indexes, and sequences, yet it does not express the foreign-key relationships that give those structures meaning. The result is friction: every schema question becomes a hunt through source code, tribal knowledge, and database tooling.

OpenEdge Schema MCP turns the schema export you already maintain into a safe, structured interface for AI-assisted development. It lets an MCP client explore the schema, inspect table context, follow reviewed relationships, and compare schema versions without connecting to a production database or exposing a connection string.

## Why it matters

An assistant can only produce trustworthy ABL, migration guidance, or documentation when it has trustworthy schema context. Without it, it may guess at field names, join paths, or key constraints. In OpenEdge, where relationships are commonly implicit rather than enforced as database foreign keys, that guesswork is especially risky.

This server gives an assistant the facts it needs in the form it can use:

- Schema discovery: list databases, tables, fields, indexes, and sequences from `.df` exports.
- Table-level context: retrieve a table's fields and indexes together with bounded, confirmed relationship context in one call.
- Reviewed relationships: store and validate domain knowledge in versionable JSON catalogs, including cross-database relationships.
- Controlled inference: suggest relationship candidates for review, but never present an inferred relationship as a fact.
- Change awareness: compare two schema exports or a schema file across Git refs and classify changes as additive, potentially migration-related, or breaking.

The result is fewer speculative tool calls, less time spent reconstructing the data model, and more reliable assistance for tasks such as writing ABL queries, reviewing a schema change, tracing a business entity across tables, or onboarding to an established application.

## Built for cautious adoption

OpenEdge Schema MCP is deliberately narrow in its access model. It runs as a separate stdio process, reads schema exports referenced by `openedge-project.json`, and never connects to an OpenEdge database. It does not return database connection strings. Teams can use a release-pinned server version and keep relationship catalogs next to the project, where changes can be reviewed through the normal Git workflow.

That makes it useful where direct database access is impractical or inappropriate: local development, offline analysis, CI review, customer environments, and modernization work with strict access boundaries.

## A practical bridge to better OpenEdge development

The project does not attempt to replace OpenEdge expertise or invent business rules. It makes existing, reviewable schema knowledge available to the tools developers already use. Start with a `.df` export and the relationships your team is confident about. Then let the assistant answer questions from evidence instead of assumptions.

OpenEdge Schema MCP makes an existing OpenEdge estate easier to understand, safer to change, and far more useful in an AI-assisted development workflow.