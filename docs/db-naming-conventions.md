# Database Naming Conventions

These conventions make OpenEdge schemas easier to read and help the OpenEdge Schema MCP suggest likely relationships from field names.

NOTE: this is a proposal, it is up to the project to implement these kind of conventions.

## General style

- Use singular, descriptive table names in PascalCase: `Customer`, `Order`, `OrderLine`.
- Use PascalCase for ordinary field names, without underscores: `Name`, `CreatedAt`, `Quantity`.
- Do not encode a field's data type in its name, as a prefix or suffix. For example, use `Name` rather than `StrName` or `NameChar`.
- Use an underscore to separate a table name from its key field name, as in `Customer_Id`.
- For role-specific foreign keys, use a hyphen between the role and referenced table, followed by the table-key separator: `<Role>-<TableName>_Id`, as in `Parent-Customer_Id`.
- Keep table, field, and index names between 1 and 32 characters, as required by OpenEdge. Allowed characters are ASCII letters (`A-Z`, `a-z`), digits (`0-9`), hyphens (`-`), and underscores (`_`).
- Validate a name with this regular expression: `^[A-Za-z0-9_-]{1,32}$`.
- Preserve the same spelling for an identifier wherever it is used. Name comparisons in the MCP are case-insensitive, but consistent casing improves readability.
- Prefer complete domain terms over abbreviations: `Customer` rather than `Cust`, unless an abbreviation is an established domain term.

## Primary keys

Name a table's primary key `<TableName>_Id` and make it unique. For example:

```text
Customer
  Customer_Id  primary key

OrderLine
  OrderLine_Id  primary key
```

Use a stable identifier whose data type and meaning can be shared by referencing fields. The convention does not require a particular physical representation, such as an integer or GUID.

## Public identifiers

Keep `<TableName>_Id` as the internal `int64` primary key for joins and foreign keys. For resources exposed through REST, add a separate `<TableName>_Pid` field for the public identifier. Generate it as a random UUIDv4 and store its standard 36-character representation in a character field. Add a unique secondary index named after the field:

```text
Customer
  Customer_Id   int64, internal primary key
  Customer_Pid  character(36), public UUID
  primary unique index pk (Customer_Id)
  unique index Customer_Pid (Customer_Pid)
```

Expose `_Pid` rather than the sequential `_Id` in REST URLs and responses. Keep `_Pid` immutable. A non-sequential identifier makes enumeration harder but does not replace authorization checks.

## Indexes

Define one primary, unique index named `pk` on each table's `<TableName>_Id` field. For example:

```text
Customer
  primary unique index pk (Customer_Id)
```

The index name is scoped to its table, so `pk` can be reused across tables. This makes the primary key easy to identify consistently in schema metadata and relationship suggestions.

For secondary indexes, name a single-field index exactly after its field. For a composite index, concatenate its field names in index order. Keep every index name within OpenEdge's 32-character limit. If the concatenated name would exceed the limit, choose a concise, descriptive name instead; do not truncate it mechanically, since that can create ambiguous or duplicate names.

```text
Order
  index Customer_Id (Customer_Id)
  index Customer_IdOrderDate (Customer_Id, OrderDate)
```

## Foreign keys

Name a foreign key exactly like the referenced primary key. Keep its data type and meaning compatible with the target key:

```text
Customer
  Customer_Id  primary key

Order
  Order_Id     primary key
  Customer_Id  foreign key -> Customer.Customer_Id

OrderLine
  OrderLine_Id  primary key
  Order_Id      foreign key -> Order.Order_Id
```

This exact-name convention is important for the current MCP implementation: `suggest_relationships` looks for matching field names and data types, and only suggests a candidate when the target field is a single-field unique index. Naming alone does not prove that a relationship exists. Review suggestions and keep confirmed relationships in the relationship catalog.

## Multiple references to the same table

When a table refers to the same target table for different roles, prefix the target table name with the role and separate them with a hyphen. For example, an invoice might have `Billing-Address_Id` and `Shipping-Address_Id`, both referencing `Address.Address_Id`.

These role-specific names intentionally do not match the target key exactly, so the current `suggest_relationships` implementation will not infer them. Configure and review these relationships explicitly in the relationship catalog. Do not rename fields to hide the distinct roles just to make them match automatically.

For a self-referential link table that connects two customers, use role names to distinguish the two references:

```text
CustomerLink
  CustomerLink_Id     primary key
  From-Customer_Id    foreign key -> Customer.Customer_Id
  To-Customer_Id      foreign key -> Customer.Customer_Id
```

Add a unique constraint on the pair of customer fields to prevent duplicate links. For an undirected relationship, also store each pair in a consistent order so that `A-B` and `B-A` cannot represent the same link twice. These role-specific foreign keys must be configured explicitly in the relationship catalog.

## Composite keys and other exceptions

Use clear, stable names for each component of a composite key and keep the field order consistent between the referencing and target indexes. The current suggester only handles a single matching field and a single-field unique target index; configure composite-key relationships explicitly.

Use the relationship catalog for self-references, cross-database references, or any relationship that cannot be expressed unambiguously with matching field names. Treat the catalog as the source of truth for confirmed relationships.
