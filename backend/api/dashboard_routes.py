import json
from fastapi import APIRouter, Depends, HTTPException
from database import get_by_id, get_all, upsert, now_iso, count, query_rows
from config import get_model_pricing, MILLION
from services.subprocess_manager import get_status as proc_status, kill_process as proc_kill
from services.pipeline_engine import stop_pipeline, stop_commands
from services.task_execution_service import stop_task as _stop_task_fn, stop_commands as _task_stop_commands
from api.auth_deps import CurrentUser, get_current_user, get_accessible_resource_ids
from api.task_routes import active_tasks as _active_tasks
from config import TOOL_RUNS_PIPELINE_ID
from models.enums import PipelineStatusType, TriggerType

router = APIRouter()

# Active statuses
ACTIVE_STATUSES = (
    PipelineStatusType.Pending,
    PipelineStatusType.Running,
    PipelineStatusType.Paused,
    PipelineStatusType.WaitingForInput,
)


def _parse_json(val, default=None):
    if isinstance(val, (dict, list)):
        return val
    if not val or not isinstance(val, str):
        return default if default is not None else {}
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _compute_run_cost(steps_json) -> float:
    """Sum cost from token counts + model pricing, matching the frontend logic."""
    steps = _parse_json(steps_json, []) if isinstance(steps_json, str) else (steps_json or [])
    total = 0.0
    for step in steps:
        for c in (step.get("call_cost") or []):
            if not isinstance(c, dict):
                continue
            m = get_model_pricing(c.get("model", ""))
            total += (c.get("input_token_count", 0) / MILLION) * m["input_cost"]
            total += (c.get("output_token_count", 0) / MILLION) * m["output_cost"]
    return round(total, 6)


def _duration_seconds(created_at: str, completed_at: str) -> float | None:
    if not created_at or not completed_at:
        return None
    from datetime import datetime, timezone
    try:
        t1 = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return round((t2 - t1).total_seconds(), 1)
    except Exception:
        return None


@router.get("")
async def get_dashboard(since: str = "", user_id: str = "", user: CurrentUser = Depends(get_current_user)):
    # Admin can filter by a specific user; non-admins always see only their own runs
    filter_user_id = ""
    if user.is_admin and user_id:
        filter_user_id = user_id
    elif not user.is_admin:
        filter_user_id = user.id
    # Counts — scoped to accessible resources for non-admin users
    if user.is_admin:
        pipeline_count = count("pipelines", where="id != ?", params=(TOOL_RUNS_PIPELINE_ID,))
        tool_count = count("tools")
        chatbot_count = count("chatbots")
        trigger_count = count("triggers")
    else:
        pipeline_count = len(get_accessible_resource_ids(user, "pipelines") or [])
        tool_count = len(get_accessible_resource_ids(user, "tools") or [])
        chatbot_count = len(get_accessible_resource_ids(user, "chatbots") or [])
        trigger_count = len(get_accessible_resource_ids(user, "triggers") or [])

    placeholders = ",".join("?" * len(ACTIVE_STATUSES))

    # Build time filter for recent runs
    from datetime import datetime, timedelta, timezone
    since_iso = ""
    if since:
        now = datetime.now(timezone.utc)
        offsets = {
            "1h": timedelta(hours=1),
            "today": timedelta(hours=now.hour, minutes=now.minute, seconds=now.second),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "365d": timedelta(days=365),
        }
        if since == "all":
            since_iso = "all"
        else:
            delta = offsets.get(since)
            if delta:
                since_iso = (now - delta).strftime("%Y-%m-%dT%H:%M:%S")

    recent_limit = 500 if since_iso else 20

    # Build run queries — filter_user_id is set for non-admins (always) and admins (when filtering)
    if filter_user_id:
        active_rows = query_rows(
            "pipeline_runs",
            where=f"status IN ({placeholders}) AND user_id = ?",
            params=(*ACTIVE_STATUSES, filter_user_id),
            order_by="created_at DESC",
        )
        if since_iso and since_iso != "all":
            recent_rows = query_rows(
                "pipeline_runs",
                where="user_id = ? AND created_at >= ?",
                params=(filter_user_id, since_iso),
                order_by="created_at DESC",
                limit=recent_limit,
            )
        else:
            recent_rows = query_rows(
                "pipeline_runs",
                where="user_id = ?",
                params=(filter_user_id,),
                order_by="created_at DESC",
                limit=recent_limit,
            )
    else:
        # Admin with no filter: see all runs
        active_rows = query_rows(
            "pipeline_runs",
            where=f"status IN ({placeholders})",
            params=ACTIVE_STATUSES,
            order_by="created_at DESC",
        )
        if since_iso and since_iso != "all":
            recent_rows = query_rows(
                "pipeline_runs",
                where="created_at >= ?",
                params=(since_iso,),
                order_by="created_at DESC",
                limit=recent_limit,
            )
        else:
            recent_rows = query_rows("pipeline_runs", order_by="created_at DESC", limit=recent_limit)

    proc_info = proc_status() if user.is_admin else {"active_count": 0, "processes": [], "job_object_active": False}

    def _run_to_dict(row, include_step_detail=False):
        d = dict(row)
        steps = _parse_json(d.get("steps", "[]"), [])
        snapshot = _parse_json(d.get("pipeline_snapshot", "{}"), {})
        total_steps = len(steps)
        current_step = d.get("current_step", 0)
        cost = _compute_run_cost(steps)
        pipeline_name = snapshot.get("name", "Unknown")

        result = {
            "id": d["id"],
            "pipeline_name": pipeline_name,
            "pipeline_id": d.get("pipeline_id", ""),
            "status": d.get("status", 0),
            "current_step": current_step,
            "total_steps": total_steps,
            "created_at": d.get("created_at", ""),
            "completed_at": d.get("completed_at", ""),
            "duration_s": _duration_seconds(d.get("created_at", ""), d.get("completed_at", "")),
            "cost": cost,
            "tool_id": d.get("tool_id", ""),
            "user_id": d.get("user_id", ""),
        }
        return result

    active_runs = [_run_to_dict(r) for r in active_rows]
    recent_runs = [_run_to_dict(r) for r in recent_rows]
    # Tag pipeline runs with run_type
    for r in active_runs:
        r["run_type"] = "pipeline"
    for r in recent_runs:
        r["run_type"] = "pipeline"

    # ── Task runs ────────────────────────────────────────────────
    # Fetch recent task runs and merge into recent_runs
    if since_iso and since_iso != "all":
        recent_task_rows = query_rows(
            "task_runs",
            where="created_at >= ?",
            params=(since_iso,),
            order_by="created_at DESC",
            limit=recent_limit,
        )
    else:
        recent_task_rows = query_rows("task_runs", order_by="created_at DESC", limit=recent_limit)

    def _task_run_to_dict(row):
        d = dict(row)
        plan = _parse_json(d.get("plan", "[]"), [])
        total_cost_data = _parse_json(d.get("total_cost", "{}"), {})
        cost = total_cost_data.get("total_cost", 0) if isinstance(total_cost_data, dict) else 0
        total_steps = len(plan)
        completed_steps = sum(1 for s in plan if s.get("status") in ("completed", "failed", "skipped"))

        # Determine task name: look up task_plan name, fall back to request
        task_name = ""
        task_plan_id = d.get("task_plan_id", "")
        if task_plan_id:
            tp = get_by_id("task_plans", task_plan_id)
            if tp:
                task_name = tp.get("name", "")
        if not task_name:
            req = d.get("request", "")
            task_name = req[:60] + ("..." if len(req) > 60 else "") if req else "Quick Task"

        # Duration: for completed/failed tasks, use created_at to updated_at
        completed_at = d.get("updated_at", "") if d.get("status") in (2, 3) else ""

        return {
            "id": d["id"],
            "pipeline_name": task_name,
            "pipeline_id": "",
            "task_plan_id": task_plan_id,
            "status": d.get("status", 0),
            "current_step": completed_steps,
            "total_steps": total_steps,
            "created_at": d.get("created_at", ""),
            "completed_at": completed_at,
            "duration_s": _duration_seconds(d.get("created_at", ""), completed_at),
            "cost": cost,
            "tool_id": "",
            "user_id": d.get("user_id", ""),
            "run_type": "task",
        }

    task_recent = [_task_run_to_dict(r) for r in recent_task_rows]
    # Merge and sort by created_at DESC
    recent_runs = sorted(recent_runs + task_recent, key=lambda x: x.get("created_at", ""), reverse=True)
    if not since_iso:
        recent_runs = recent_runs[:20]

    # ── Active tasks (in-memory) ─────────────────────────────────
    active_task_list = []
    for run_id, info in list(_active_tasks.items()):
        active_task_list.append({
            "id": run_id,
            "task_plan_id": info.get("task_plan_id", ""),
            "task_name": info.get("task_name", "Task"),
            "request": info.get("request", ""),
            "current_step_name": info.get("current_step_name", ""),
            "total_steps": info.get("total_steps", 0),
            "created_at": info.get("created_at", ""),
        })

    # Active (enabled) triggers
    type_names = {
        TriggerType.Cron: "Cron",
        TriggerType.FileWatcher: "File Watcher",
        TriggerType.Webhook: "Webhook",
        TriggerType.RSS: "RSS",
        TriggerType.Custom: "Custom",
    }
    all_triggers = get_all("triggers", order_by="sort_index")
    if not user.is_admin:
        accessible_trigger_ids = get_accessible_resource_ids(user, "triggers")
        if accessible_trigger_ids is not None:
            all_triggers = [t for t in all_triggers if t["id"] in accessible_trigger_ids]
    active_triggers = []
    for t in all_triggers:
        if not t.get("is_enabled"):
            continue
        conns = t.get("connections") or []
        if isinstance(conns, str):
            conns = _parse_json(conns, [])
        active_triggers.append({
            "id": t["id"],
            "name": t.get("name", ""),
            "trigger_type": t.get("trigger_type", 0),
            "trigger_type_label": type_names.get(t.get("trigger_type", 0), "Unknown"),
            "last_fired_at": t.get("last_fired_at", ""),
            "last_status": t.get("last_status", ""),
            "fire_count": t.get("fire_count", 0),
            "connections_count": len(conns),
        })

    return {
        "stats": {
            "pipelines": pipeline_count,
            "tools": tool_count,
            "chatbots": chatbot_count,
            "triggers": trigger_count,
            "active_runs": len(active_runs),
            "active_processes": proc_info["active_count"],
            "active_triggers": len(active_triggers),
            "active_tasks": len(active_task_list),
        },
        "active_runs": active_runs,
        "active_tasks": active_task_list,
        "active_triggers": active_triggers,
        "processes": proc_info["processes"],
        "recent_runs": recent_runs,
        "job_object_active": proc_info["job_object_active"],
    }


@router.post("/runs/{run_id}/stop")
async def force_stop_run(run_id: str, user: CurrentUser = Depends(get_current_user)):
    """Force-stop a run: sets the in-memory flag AND directly updates DB status.

    This handles abandoned runs where no asyncio task is checking stop_commands.
    """
    # Regular users can only stop their own runs
    run = get_by_id("pipeline_runs", run_id)
    if not user.is_admin and run and run.get("user_id", "default") != user.id:
        raise HTTPException(403, "Cannot stop another user's run")

    # Set the flag in case a task IS still running
    stop_pipeline(run_id)

    # Directly update DB for abandoned runs with no active task
    if run and run.get("status") in ACTIVE_STATUSES:
        run["status"] = PipelineStatusType.Failed
        run["completed_at"] = now_iso()
        # Mark any still-active steps as failed too
        for step in (run.get("steps") or []):
            if step.get("status") in ACTIVE_STATUSES:
                step["status"] = PipelineStatusType.Failed
                step["status_text"] = "Force-stopped from dashboard"
        upsert("pipeline_runs", run)
        stop_commands.discard(run_id)
        return {"success": True, "forced": True}

    return {"success": True, "forced": False}


@router.post("/task-runs/{run_id}/stop")
async def force_stop_task_run(run_id: str, user: CurrentUser = Depends(get_current_user)):
    """Force-stop a task run from the dashboard."""
    _stop_task_fn(run_id)

    if run_id in _active_tasks:
        info = _active_tasks[run_id]
        atask = info.get("asyncio_task")
        if atask and not atask.done():
            atask.cancel()
        _active_tasks.pop(run_id, None)

    # Update DB status
    run = get_by_id("task_runs", run_id)
    if run and run.get("status") in ACTIVE_STATUSES:
        run["status"] = PipelineStatusType.Failed
        run["updated_at"] = now_iso()
        for step in (run.get("plan") or []):
            if step.get("status") == "running":
                step["status"] = "failed"
                step["output"] = "Force-stopped from dashboard"
        upsert("task_runs", run)
        _task_stop_commands.discard(run_id)
        return {"success": True, "forced": True}

    return {"success": True, "forced": False}


@router.post("/processes/{pid}/kill")
async def kill_process(pid: int):
    success = proc_kill(pid)
    return {"success": success}
