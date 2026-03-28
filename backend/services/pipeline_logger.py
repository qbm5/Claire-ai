"""
Pipeline execution logger - broadcasts structured run_log events via SSE
and persists entries in memory for later retrieval.
"""

from datetime import datetime, timezone
from event_bus import broadcast

# In-memory log store: run_id -> list of entries
_run_logs: dict[str, list[dict]] = {}

MAX_ENTRIES_PER_RUN = 500


def run_log(
    run_id: str,
    source: str,
    message: str,
    *,
    step_id: str = "",
    level: str = "info",
    detail: dict | None = None,
):
    """Broadcast and store a structured log entry for a pipeline run."""
    entry = {
        "run_id": run_id,
        "step_id": step_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "source": source,
        "message": message,
    }
    if detail:
        entry["detail"] = detail
    broadcast("run_log", entry)

    # Persist in memory
    if run_id not in _run_logs:
        _run_logs[run_id] = []
    _run_logs[run_id].append(entry)
    if len(_run_logs[run_id]) > MAX_ENTRIES_PER_RUN:
        _run_logs[run_id] = _run_logs[run_id][-MAX_ENTRIES_PER_RUN:]


def get_log_entries(run_id: str) -> list[dict]:
    """Return stored log entries for a run."""
    return _run_logs.get(run_id, [])


def flush_to_run(run_id: str, pipeline_run: dict) -> None:
    """Write accumulated log entries into the pipeline_run dict and free memory."""
    entries = _run_logs.pop(run_id, None)
    if entries:
        pipeline_run["log_entries"] = entries


def clear_log(run_id: str) -> None:
    """Remove in-memory log entries for a run."""
    _run_logs.pop(run_id, None)
