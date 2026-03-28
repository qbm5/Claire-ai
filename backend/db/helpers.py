import json
import uuid
from datetime import datetime, timezone


def get_uid() -> str:
    return str(uuid.uuid4())[:8]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── JSON / Bool column maps ─────────────────────────────────────────

BOOL_COLS = {
    "chatbots": ["is_enabled"],
    "tools": ["is_enabled"],
    "triggers": ["is_enabled"],
    "task_plans": ["is_enabled", "auto_run"],
    "users": ["is_active", "must_change_password"],
    "role_permissions": ["can_create", "can_edit", "can_delete", "can_use"],
    "user_permissions": ["can_create", "can_edit", "can_delete"],
}

JSON_COLS = {
    "chatbots": ["source_texts"],
    "chat_histories": ["messages"],
    "tools": ["agent_functions", "request_inputs", "pip_dependencies", "env_variables", "mcp_servers", "endpoint_headers", "endpoint_body", "endpoint_query", "response_structure"],
    "pipelines": ["steps", "inputs", "edges", "memories"],
    "pipeline_runs": ["pipeline_snapshot", "steps", "inputs", "outputs", "rerun_from", "memories", "log_entries"],
    "pipeline_memories": ["messages"],
    "triggers": ["watch_events", "pip_dependencies", "env_variables", "outputs", "connections"],
    "task_plans": ["inputs", "plan"],
    "task_runs": ["input_values", "plan", "total_cost"],
}


def serialize_row(table: str, data: dict) -> dict:
    """Convert Python lists/dicts to JSON strings for storage."""
    out = dict(data)
    for col in JSON_COLS.get(table, []):
        if col in out and not isinstance(out[col], str):
            out[col] = json.dumps(out[col])
    return out


def deserialize_row(table: str, row: dict) -> dict:
    """Convert JSON strings back to Python objects, integers back to bools."""
    d = dict(row)
    for col in JSON_COLS.get(table, []):
        if col in d and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    for col in BOOL_COLS.get(table, []):
        if col in d:
            d[col] = bool(d[col])
    return d
