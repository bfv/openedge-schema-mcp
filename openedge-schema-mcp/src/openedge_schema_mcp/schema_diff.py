"""Compare exported OpenEdge schemas without connecting to a database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import re
import subprocess
from pathlib import Path, PureWindowsPath
from typing import Any

from .schema import DatabaseSchema, Field, Index, Table, parse_df, parse_df_contents


_FIELD_ATTRIBUTES = (
    "data_type",
    "format",
    "initial",
    "validation_expression",
    "validation_message",
    "mandatory",
    "label",
    "help_text",
)
_SEQUENCE_ATTRIBUTES = ("initial", "increment", "minimum", "cycle_on_limit")


def compare_schema_versions(
    base_schema_file: str | None = None,
    target_schema_file: str | None = None,
    base_ref: str | None = None,
    target_ref: str | None = None,
    schema_file: str | None = None,
    database: str | None = None,
    include_delta_df: bool = False,
) -> dict[str, object]:
    """Compare two local schema files or one schema path across two Git refs."""
    file_mode = base_schema_file is not None or target_schema_file is not None
    git_mode = base_ref is not None or target_ref is not None or schema_file is not None
    if file_mode == git_mode:
        raise ValueError("Provide exactly one comparison mode: two schema files or two Git refs and schema_file.")

    if file_mode:
        if not base_schema_file or not target_schema_file:
            raise ValueError("File comparison requires both base_schema_file and target_schema_file.")
        base_path = Path(base_schema_file).expanduser().resolve()
        target_path = Path(target_schema_file).expanduser().resolve()
        _validate_df_path(base_schema_file)
        _validate_df_path(target_schema_file)
        base = parse_df(database or target_path.stem, base_path)
        target = parse_df(database or target_path.stem, target_path)
        source = {
            "mode": "files",
            "base": str(base_path),
            "target": str(target_path),
        }
        database_name = database or target_path.stem
    else:
        if not base_ref or not target_ref or not schema_file:
            raise ValueError("Git comparison requires base_ref, target_ref, and schema_file.")
        relative_path = _workspace_relative_schema_path(schema_file)
        repository_root = _git_repository_root()
        base_contents = _git_schema_contents(repository_root, base_ref, relative_path)
        target_contents = _git_schema_contents(repository_root, target_ref, relative_path)
        database_name = database or Path(relative_path).stem
        base = parse_df_contents(database_name, base_contents, relative_path)
        target = parse_df_contents(database_name, target_contents, relative_path)
        source = {
            "mode": "git_refs",
            "base": f"{base_ref}:{relative_path}",
            "target": f"{target_ref}:{relative_path}",
        }

    result = _diff_schemas(base, target, database_name, source)
    if include_delta_df:
        result["delta_df"] = _render_delta_df(base, target, result)
    return result


def _workspace_relative_schema_path(schema_file: str) -> str:
    path = Path(schema_file)
    if (
        not schema_file.strip()
        or path.is_absolute()
        or PureWindowsPath(schema_file).is_absolute()
        or ".." in path.parts
    ):
        raise ValueError("schema_file must be a workspace-relative .df path.")
    _validate_df_path(schema_file, "schema_file")
    return path.as_posix()


def _validate_df_path(schema_file: str, argument: str = "schema file") -> None:
    if not schema_file.strip() or Path(schema_file).suffix.casefold() != ".df":
        raise ValueError(f"{argument} must identify a .df file.")


def _git_repository_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("Git ref comparison requires a Git workspace.") from error
    return Path(result.stdout.strip())


def _git_schema_contents(repository_root: Path, ref: str, schema_file: str) -> bytes:
    revision_path = f"{ref}:{schema_file}"
    try:
        result = subprocess.run(
            ["git", "show", "--format=", "--end-of-options", revision_path],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            detail = error.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"Could not read Git schema '{revision_path}'{suffix}") from error
    return result.stdout


def _diff_schemas(
    base: DatabaseSchema,
    target: DatabaseSchema,
    database: str,
    source: dict[str, str],
) -> dict[str, object]:
    summary = {
        "additive_changes": 0,
        "potential_data_migrations": 0,
        "breaking_changes": 0,
    }
    table_diff = _diff_named_objects(
        base.tables,
        target.tables,
        lambda old, new: _diff_table(old, new, summary),
        summary,
        removed_reason="Removing a table can break consumers of its schema.",
    )
    sequence_diff = _diff_sequences(base, target, summary)
    return {
        "database": database,
        "source": source,
        "tables": table_diff,
        "sequences": sequence_diff,
        "summary": summary,
    }


def _render_delta_df(
    base: DatabaseSchema, target: DatabaseSchema, diff: dict[str, object]
) -> str:
    tables_diff = diff["tables"]
    sequences_diff = diff["sequences"]
    if not isinstance(tables_diff, dict) or not isinstance(sequences_diff, dict):
        raise ValueError("Could not render a delta .df from the schema comparison.")

    add_tables: list[str] = []
    add_fields: list[str] = []
    add_indexes: list[str] = []
    updates: list[str] = []
    drop_indexes: list[str] = []
    drop_fields: list[str] = []
    drop_sequences: list[str] = []
    drop_tables: list[str] = []

    added_table_names = set(tables_diff["added"])
    removed_table_names = set(tables_diff["removed"])
    for table_name in sorted(added_table_names, key=_sort_key):
        table = target.tables[table_name]
        add_tables.append(_definition(target, ("table", table.name)))
        add_fields.extend(
            _definition(target, ("field", table.name, field.name))
            for field in sorted(table.fields, key=lambda item: _sort_key(item.name))
        )
        add_indexes.extend(
            _definition(target, ("index", table.name, index.name))
            for index in sorted(table.indexes, key=lambda item: _sort_key(item.name))
        )

    for table_name in sorted(removed_table_names, key=_sort_key):
        drop_tables.append(f'DROP TABLE "{table_name}"')

    modified_tables = tables_diff["modified"]
    if not isinstance(modified_tables, list):
        raise ValueError("Could not render a delta .df from the schema comparison.")
    primary_index_updates: list[str] = []
    for table_diff in modified_tables:
        if not isinstance(table_diff, dict):
            continue
        table_name = table_diff["name"]
        old_table = base.tables[table_name]
        new_table = target.tables[table_name]

        table_changes = table_diff.get("changes", {})
        if table_changes:
            if not isinstance(table_changes, dict):
                raise ValueError(f"Could not render table changes for '{table_name}'.")
            properties: list[str] = []
            for attribute, property_name in (
                ("description", "DESCRIPTION"),
                ("dump_name", "DUMP-NAME"),
            ):
                if attribute in table_changes:
                    properties.append(
                        _updated_property(
                            target,
                            ("table", table_name),
                            property_name,
                        )
                    )
            if "triggers" in table_changes:
                removed_triggers = set(old_table.triggers) - set(new_table.triggers)
                if removed_triggers:
                    raise ValueError(
                        f"Delta export does not support removing table triggers on '{table_name}'."
                    )
                properties.extend(
                    line.strip()
                    for line in _definition(target, ("table", table_name)).splitlines()
                    if line.lstrip().startswith("TABLE-TRIGGER ")
                )
            if properties:
                updates.append(f'UPDATE TABLE "{table_name}"\n' + "\n".join(f"  {line}" for line in properties))

        fields_diff = table_diff["fields"]
        if not isinstance(fields_diff, dict):
            raise ValueError(f"Could not render field changes for '{table_name}'.")
        for field_name in sorted(fields_diff["added"], key=_sort_key):
            add_fields.append(_definition(target, ("field", table_name, field_name)))
        for field_name in sorted(fields_diff["removed"], key=_sort_key):
            drop_fields.append(f'DROP FIELD "{field_name}" OF "{table_name}"')
        for field_diff in fields_diff["modified"]:
            updates.append(_render_field_update(target, table_name, field_diff))

        indexes_diff = table_diff["indexes"]
        if not isinstance(indexes_diff, dict):
            raise ValueError(f"Could not render index changes for '{table_name}'.")
        for index_name in sorted(indexes_diff["added"], key=_sort_key):
            add_indexes.append(_definition(target, ("index", table_name, index_name)))
        for index_name in sorted(indexes_diff["removed"], key=_sort_key):
            drop_indexes.append(f'DROP INDEX "{index_name}" ON "{table_name}"')
        for index_diff in indexes_diff["modified"]:
            index_name = index_diff["name"]
            drop_indexes.append(f'DROP INDEX "{index_name}" ON "{table_name}"')
            add_indexes.append(_definition(target, ("index", table_name, index_name)))

        old_primary = next((index.name for index in old_table.indexes if index.primary), None)
        new_primary = next((index.name for index in new_table.indexes if index.primary), None)
        if old_primary != new_primary and new_primary is not None:
            primary_index_updates.append(
                f'UPDATE PRIMARY INDEX "{new_primary}" ON "{table_name}"'
            )

    for sequence_name in sorted(sequences_diff["added"], key=_sort_key):
        add_sequences = _definition(target, ("sequence", sequence_name))
        updates.append(add_sequences)
    for sequence_diff in sequences_diff["modified"]:
        updates.append(_render_sequence_update(target, sequence_diff))
    for sequence_name in sorted(sequences_diff["removed"], key=_sort_key):
        drop_sequences.append(f'DROP SEQUENCE "{sequence_name}"')

    blocks = [
        *add_tables,
        *add_fields,
        *updates,
        *drop_indexes,
        *add_indexes,
        *primary_index_updates,
        *drop_fields,
        *drop_sequences,
        *drop_tables,
    ]
    definition_data = ("\r\n\r\n".join(blocks) + "\r\n\r\n.\r\n").replace(
        "\r\n", "\n"
    ).replace("\n", "\r\n")
    footer_length = len(definition_data.encode("utf-8"))
    return f"{definition_data}PSC\r\ncpstream=UTF-8\r\n.\r\n{footer_length:010d}\r\n"


def _render_field_update(
    target: DatabaseSchema, table_name: str, field_diff: dict[str, object]
) -> str:
    field_name = str(field_diff["name"])
    field = next(field for field in target.tables[table_name].fields if field.name == field_name)
    changes = field_diff["changes"]
    if not isinstance(changes, dict):
        raise ValueError(f"Could not render field changes for '{field_name}'.")
    header = f'UPDATE FIELD "{field_name}" OF "{table_name}"'
    if "data_type" in changes:
        header += f" AS {field.data_type}"
    properties = [
        _updated_property(target, ("field", table_name, field_name), property_name, field.mandatory)
        for attribute, property_name in (
            ("format", "FORMAT"),
            ("initial", "INITIAL"),
            ("validation_expression", "VALEXP"),
            ("validation_message", "VALMSG"),
            ("label", "LABEL"),
            ("help_text", "HELP"),
            ("mandatory", "MANDATORY"),
        )
        if attribute in changes
    ]
    return "\n".join([header, *(f"  {property_line}" for property_line in properties)])


def _render_sequence_update(
    target: DatabaseSchema, sequence_diff: dict[str, object]
) -> str:
    sequence_name = str(sequence_diff["name"])
    changes = sequence_diff["changes"]
    if not isinstance(changes, dict):
        raise ValueError(f"Could not render sequence changes for '{sequence_name}'.")
    properties = [
        _updated_property(target, ("sequence", sequence_name), property_name)
        for attribute, property_name in (
            ("initial", "INITIAL"),
            ("increment", "INCREMENT"),
            ("minimum", "MIN-VAL"),
            ("cycle_on_limit", "CYCLE-ON-LIMIT"),
        )
        if attribute in changes
    ]
    return "\n".join(
        [f'UPDATE SEQUENCE "{sequence_name}"', *(f"  {property_line}" for property_line in properties)]
    )


def _definition(schema: DatabaseSchema, key: tuple[str, ...]) -> str:
    try:
        return schema.definitions[key].replace("\r\n", "\n").replace("\n", "\r\n")
    except KeyError as error:
        raise ValueError(f"Could not find the source definition for {key!r}.") from error


def _updated_property(
    schema: DatabaseSchema,
    key: tuple[str, ...],
    property_name: str,
    mandatory: bool | None = None,
) -> str:
    if property_name == "MANDATORY":
        return "MANDATORY" if mandatory else "MANDATORY no"
    for line in _definition(schema, key).splitlines():
        stripped = line.strip()
        if stripped.casefold() == property_name.casefold() or stripped.casefold().startswith(
            f"{property_name.casefold()} "
        ):
            return stripped
    return f"{property_name} ?"


def _diff_table(
    old: Table, new: Table, summary: dict[str, int]
) -> dict[str, object] | None:
    fields = _diff_named_objects(
        {field.name: field for field in old.fields},
        {field.name: field for field in new.fields},
        lambda first, second: _diff_field(first, second, summary),
        summary,
        removed_reason="Removing a field can break consumers and discard stored data.",
        added_field=True,
    )
    indexes = _diff_indexes(old, new, summary)
    changes = _attribute_changes(old, new, ("description", "dump_name", "triggers"))
    if not fields["added"] and not fields["removed"] and not fields["modified"] \
            and not indexes["added"] and not indexes["removed"] and not indexes["modified"] \
            and not changes:
        return None
    result: dict[str, object] = {
        "name": old.name,
        "fields": fields,
        "indexes": indexes,
    }
    if changes:
        result["changes"] = changes
        result["classification"] = "potential_data_migration"
        result["reason"] = "Changing table metadata or triggers may alter schema behavior."
        summary["potential_data_migrations"] += 1
    return result


def _diff_field(
    old: Field, new: Field, summary: dict[str, int]
) -> dict[str, object] | None:
    changes = _attribute_changes(old, new, _FIELD_ATTRIBUTES)
    if not changes:
        return None

    if "data_type" in changes:
        classification = "breaking"
        reason = "Changing a field data type can require conversion of existing data."
    elif _character_length_reduced(old, new):
        classification = "potential_data_migration"
        reason = (
            "Reducing a character field format length does not truncate stored data "
            "(OpenEdge stores variable length), but can truncate display or input."
        )
    elif changes.get("mandatory") == {"from": False, "to": True}:
        classification = "potential_data_migration"
        reason = "Making a field mandatory can fail when existing rows have no value."
    elif "mandatory" in changes:
        classification = "potential_data_migration"
        reason = "Changing whether a field is mandatory can affect existing rows."
    else:
        classification = "potential_data_migration"
        changed_attribute = next(iter(changes))
        reason = f"Changing field {changed_attribute.replace('_', ' ')} may require data or application updates."
    summary_key = (
        "breaking_changes" if classification == "breaking" else "potential_data_migrations"
    )
    summary[summary_key] += 1
    return {
        "name": old.name,
        "changes": changes,
        "classification": classification,
        "reason": reason,
    }


def _character_length_reduced(old: Field, new: Field) -> bool:
    if "char" not in old.data_type.casefold() or "char" not in new.data_type.casefold():
        return False
    old_length = _character_length(old)
    new_length = _character_length(new)
    return old_length is not None and new_length is not None and new_length < old_length


def _character_length(field: Field) -> int | None:
    for value in (field.data_type, field.format or ""):
        match = re.search(r"(?:x\s*\(\s*(\d+)\s*\)|character\s*\(\s*(\d+)\s*\))", value, re.I)
        if match:
            return int(match.group(1) or match.group(2))
    return None


def _diff_indexes(
    old: Table, new: Table, summary: dict[str, int]
) -> dict[str, object]:
    old_indexes = {index.name: index for index in old.indexes}
    new_indexes = {index.name: index for index in new.indexes}
    added = sorted(new_indexes.keys() - old_indexes.keys(), key=_sort_key)
    removed = sorted(old_indexes.keys() - new_indexes.keys(), key=_sort_key)
    modified: list[dict[str, object]] = []
    key_added: list[str] = []
    key_removed: list[str] = []
    key_modified: list[str] = []

    for name in added:
        index = new_indexes[name]
        key_index = index.primary or index.unique
        if key_index:
            key_added.append(name)
            summary["breaking_changes"] += 1
        else:
            summary["additive_changes"] += 1
    for name in removed:
        index = old_indexes[name]
        if index.primary or index.unique:
            key_removed.append(name)
    for name in sorted(old_indexes.keys() & new_indexes.keys(), key=_sort_key):
        before = old_indexes[name]
        after = new_indexes[name]
        changes = _attribute_changes(before, after, ("fields", "primary", "unique"))
        if not changes:
            continue
        is_key_change = (
            before.primary or before.unique or after.primary or after.unique
        )
        if is_key_change:
            classification = "breaking"
            reason = "Changing a primary or unique index can invalidate keys or dependent data."
            key_modified.append(name)
            summary["breaking_changes"] += 1
        else:
            classification = "potential_data_migration"
            reason = "Changing an index definition can affect validation and query behavior."
            summary["potential_data_migrations"] += 1
        modified.append(
            {
                "name": name,
                "changes": changes,
                "classification": classification,
                "reason": reason,
            }
        )

    summary["breaking_changes"] += len(removed)
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "added_details": [
            {
                "name": name,
                "classification": (
                    "breaking"
                    if new_indexes[name].primary or new_indexes[name].unique
                    else "additive"
                ),
                **(
                    {"reason": "Adding a primary or unique index can constrain or invalidate existing data."}
                    if new_indexes[name].primary or new_indexes[name].unique
                    else {}
                ),
            }
            for name in added
        ],
        "removed_classification": "breaking",
        "removed_reason": "Removing an index can break consumers or remove a key constraint.",
        "primary_or_unique": {
            "added": sorted(set(key_added), key=_sort_key),
            "removed": sorted(set(key_removed), key=_sort_key),
            "modified": key_modified,
        },
    }


def _diff_sequences(
    base: DatabaseSchema, target: DatabaseSchema, summary: dict[str, int]
) -> dict[str, object]:
    old_sequences = {sequence.name: sequence for sequence in base.sequences}
    new_sequences = {sequence.name: sequence for sequence in target.sequences}
    added = sorted(new_sequences.keys() - old_sequences.keys(), key=_sort_key)
    removed = sorted(old_sequences.keys() - new_sequences.keys(), key=_sort_key)
    modified: list[dict[str, object]] = []
    summary["additive_changes"] += len(added)
    summary["breaking_changes"] += len(removed)
    for name in sorted(old_sequences.keys() & new_sequences.keys(), key=_sort_key):
        changes = _attribute_changes(
            old_sequences[name], new_sequences[name], _SEQUENCE_ATTRIBUTES
        )
        if changes:
            modified.append(
                {
                    "name": name,
                    "changes": changes,
                    "classification": "potential_data_migration",
                    "reason": "Changing sequence settings can alter generated values.",
                }
            )
            summary["potential_data_migrations"] += 1
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "added_classification": "additive",
        "removed_classification": "breaking",
        "removed_reason": "Removing a sequence can break code that requests its values.",
    }


def _diff_named_objects(
    old_objects: dict[str, Any],
    new_objects: dict[str, Any],
    compare: Callable[[Any, Any], dict[str, object] | None],
    summary: dict[str, int],
    *,
    removed_reason: str,
    added_field: bool = False,
) -> dict[str, object]:
    added = sorted(new_objects.keys() - old_objects.keys(), key=_sort_key)
    removed = sorted(old_objects.keys() - new_objects.keys(), key=_sort_key)
    modified: list[dict[str, object]] = []
    if added_field:
        fields = [new_objects[name] for name in added]
        for field in fields:
            if field.mandatory:
                summary["potential_data_migrations"] += 1
            else:
                summary["additive_changes"] += 1
    else:
        summary["additive_changes"] += len(added)
    summary["breaking_changes"] += len(removed)
    for name in sorted(old_objects.keys() & new_objects.keys(), key=_sort_key):
        difference = compare(old_objects[name], new_objects[name])
        if difference is not None:
            modified.append(difference)
    result: dict[str, object] = {"added": added, "removed": removed, "modified": modified}
    if added_field:
        result["added_details"] = [
            {
                "name": field.name,
                "classification": (
                    "potential_data_migration" if field.mandatory else "additive"
                ),
                **(
                    {"reason": "Adding a mandatory field can fail for existing rows without a value."}
                    if field.mandatory
                    else {}
                ),
            }
            for field in (new_objects[name] for name in added)
        ]
    else:
        result["added_classification"] = "additive"
    if removed:
        result["removed_classification"] = "breaking"
        result["removed_reason"] = removed_reason
    return result


def _attribute_changes(
    old: object, new: object, attributes: tuple[str, ...]
) -> dict[str, dict[str, object]]:
    old_values = asdict(old)
    new_values = asdict(new)
    return {
        attribute: {"from": old_values[attribute], "to": new_values[attribute]}
        for attribute in attributes
        if old_values[attribute] != new_values[attribute]
    }


def _sort_key(name: str) -> tuple[str, str]:
    return name.casefold(), name
