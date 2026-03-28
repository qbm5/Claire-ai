"""
Custom variable service — DB-backed per-resource variable storage.
"""

from database import get_all, upsert, delete_by_id
from db.helpers import get_uid, now_iso
from models.enums import PropertyType


def get_vars_for_resource(resource_type: str, resource_id: str) -> dict[str, str]:
    """Return {name: value} for a specific tool/trigger."""
    rows = get_all(
        "custom_variables",
        "resource_type = ? AND resource_id = ?",
        (resource_type, resource_id),
    )
    return {r["name"]: r["value"] for r in rows}


def get_all_groups() -> list[dict]:
    """Return all custom variables grouped by resource (tools AND triggers).

    Merges DB values with env_variable schemas from tool/trigger records so that
    description and type metadata are always current.
    """
    all_vars = get_all("custom_variables")

    # Index DB rows by (resource_type, resource_id, name)
    db_index: dict[tuple[str, str, str], dict] = {}
    for row in all_vars:
        key = (row["resource_type"], row["resource_id"], row["name"])
        db_index[key] = row

    groups: list[dict] = []

    def _build_groups(items: list[dict], resource_type: str):
        for item in items:
            env_vars = item.get("env_variables", [])
            if not env_vars:
                continue
            variables = []
            for var in env_vars:
                name = var.get("name", "").strip()
                if not name:
                    continue
                db_row = db_index.get((resource_type, item["id"], name))
                variables.append({
                    "name": name,
                    "description": var.get("description", ""),
                    "type": var.get("type", PropertyType.TEXT),
                    "value": db_row["value"] if db_row else "",
                })
            if variables:
                groups.append({
                    "resource_type": resource_type,
                    "resource_id": item["id"],
                    "resource_name": item.get("name", ""),
                    "variables": variables,
                })

    _build_groups(get_all("tools"), "tool")
    _build_groups(get_all("triggers"), "trigger")

    return groups


def sync_var_schema(resource_type: str, resource_id: str, env_variables: list[dict]):
    """Sync DB rows with declared env_variable names.

    Creates rows for newly declared names (empty value), deletes rows for removed
    names.  Never overwrites existing values.
    """
    existing = get_all(
        "custom_variables",
        "resource_type = ? AND resource_id = ?",
        (resource_type, resource_id),
    )
    existing_by_name = {r["name"]: r for r in existing}

    declared_names = {v.get("name", "").strip() for v in (env_variables or []) if v.get("name", "").strip()}

    now = now_iso()

    # Create rows for new names
    for name in declared_names:
        if name not in existing_by_name:
            upsert("custom_variables", {
                "id": get_uid(),
                "resource_type": resource_type,
                "resource_id": resource_id,
                "name": name,
                "value": "",
                "created_at": now,
                "updated_at": now,
            })

    # Delete rows for removed names
    for name, row in existing_by_name.items():
        if name not in declared_names:
            delete_by_id("custom_variables", row["id"])


def delete_vars_for_resource(resource_type: str, resource_id: str):
    """Delete all custom variables for a resource (used on tool/trigger deletion)."""
    rows = get_all(
        "custom_variables",
        "resource_type = ? AND resource_id = ?",
        (resource_type, resource_id),
    )
    for row in rows:
        delete_by_id("custom_variables", row["id"])
