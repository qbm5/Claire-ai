import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from database import get_all, get_by_id, upsert, delete_by_id, get_uid, now_iso, query_rows
from api.auth_deps import CurrentUser, get_current_user, ws_get_current_user
from services.task_execution_service import (
    generate_plan, execute_plan, stop_task, stop_commands,
    STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_WAITING,
)

router = APIRouter()

# ── In-memory active task tracking ───────────────────────────────
# Maps run_id -> { task_plan_id, task_name, request, current_step_name,
#                  total_steps, created_at, asyncio_task }
active_tasks: dict[str, dict] = {}


# ── Task runs (static paths must come before /{plan_id}) ─────────

@router.get("/runs/all")
async def list_all_task_runs(user: CurrentUser = Depends(get_current_user)):
    """Get all recent task runs across all task plans, sorted by created_at DESC."""
    return query_rows("task_runs", order_by="created_at DESC", limit=50)


@router.get("/runs/{run_id}/detail")
async def get_task_run_detail(run_id: str, user: CurrentUser = Depends(get_current_user)):
    """Get a single task run by its ID with full details."""
    run = get_by_id("task_runs", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Task run not found")
    return run


@router.delete("/runs/{run_id}")
async def delete_task_run(run_id: str, user: CurrentUser = Depends(get_current_user)):
    delete_by_id("task_runs", run_id)
    return {"response": "ok"}


@router.post("/runs/{run_id}/stop")
async def stop_task_run(run_id: str, user: CurrentUser = Depends(get_current_user)):
    """Stop a running task — signals stop_commands and cancels the asyncio task."""
    # Signal the execution service to stop (checked by execute_plan and agent loops)
    stop_task(run_id)

    if run_id in active_tasks:
        info = active_tasks[run_id]
        atask = info.get("asyncio_task")
        if atask and not atask.done():
            atask.cancel()
        # Update DB status
        run = get_by_id("task_runs", run_id)
        if run and run.get("status") in (STATUS_PENDING, STATUS_RUNNING, STATUS_WAITING):
            run["status"] = STATUS_FAILED
            run["updated_at"] = now_iso()
            # Mark running steps as failed
            for step in (run.get("plan") or []):
                if step.get("status") == "running":
                    step["status"] = "failed"
                    step["output"] = "Stopped by user"
            upsert("task_runs", run)
        active_tasks.pop(run_id, None)
        stop_commands.discard(run_id)
        return {"success": True}
    # Fallback: update DB directly for orphaned runs
    run = get_by_id("task_runs", run_id)
    if run and run.get("status") in (STATUS_PENDING, STATUS_RUNNING, STATUS_WAITING):
        run["status"] = STATUS_FAILED
        run["updated_at"] = now_iso()
        upsert("task_runs", run)
        return {"success": True}
    return {"success": False, "reason": "not found or not active"}


# ── CRUD for task_plans ──────────────────────────────────────────

@router.get("")
async def list_task_plans(user: CurrentUser = Depends(get_current_user)):
    return get_all("task_plans", order_by="sort_index")


@router.get("/{plan_id}")
async def get_task_plan(plan_id: str):
    plan = get_by_id("task_plans", plan_id)
    if not plan:
        return {"error": "not found"}
    return plan


@router.post("")
async def save_task_plan(data: dict, user: CurrentUser = Depends(get_current_user)):
    data["updated_at"] = now_iso()
    if not data.get("created_at"):
        data["created_at"] = now_iso()
    upsert("task_plans", data)
    return {"response": "ok"}


@router.delete("/{plan_id}")
async def delete_task_plan(plan_id: str, user: CurrentUser = Depends(get_current_user)):
    delete_by_id("task_plans", plan_id)
    # Also delete associated runs
    runs = get_all("task_runs", "task_plan_id = ?", (plan_id,))
    for r in runs:
        delete_by_id("task_runs", r["id"])
    return {"response": "ok"}


@router.get("/{plan_id}/runs")
async def list_task_runs(plan_id: str, user: CurrentUser = Depends(get_current_user)):
    return get_all("task_runs", "task_plan_id = ?", (plan_id,), order_by="created_at DESC")


# ── WebSocket: Plan & Execute ────────────────────────────────────

async def ws_task_execute(ws: WebSocket):
    """WebSocket for task planning and execution.

    Client sends:
      {"request": "...", "model": "...", "task_plan_id": "optional", "input_values": {...},
       "saved_plan": [...], "auto_run": true/false}

    Server sends events:
      {"type": "status", "text": "..."}
      {"type": "plan", "plan": {...}, "planning_cost": {...}}
      {"type": "step_start", "step_id": "...", "name": "..."}
      {"type": "step_delta", "step_id": "...", "text": "..."}
      {"type": "step_complete", "step_id": "...", "output": "...", "cost": {...}}
      {"type": "step_error", "step_id": "...", "error": "..."}
      {"type": "ask_user", "step_id": "...", "questions": [...]}
      {"type": "complete", "run_id": "...", "output": "...", "total_cost": {...}}
      {"type": "error", "text": "..."}

    Client can send during execution:
      {"action": "answer", "step_id": "...", "answers": [...]}
      {"action": "approve"}       -- when auto_run=false, approve plan to start execution
      {"action": "approve_step"}  -- when auto_run=false, approve next step
      {"action": "skip_step", "step_id": "..."}  -- skip a step
    """
    try:
        user = await ws_get_current_user(ws)
    except Exception:
        return
    await ws.accept()

    # Pending answers: step_id -> {event, answers}
    pending_answers: dict[str, dict] = {}
    # Approval events for manual mode
    plan_approved = asyncio.Event()
    step_approved = asyncio.Event()
    skip_steps: set[str] = set()

    async def ws_send(msg: dict):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            pass

    async def wait_for_answer(step_id: str) -> list:
        """Wait for user to submit answers for an ask_user step."""
        event = asyncio.Event()
        pending_answers[step_id] = {"event": event, "answers": None}
        try:
            await asyncio.wait_for(event.wait(), timeout=600)
        except asyncio.TimeoutError:
            return [{"id": "timeout", "answer": "(no response — timed out)"}]
        result = pending_answers.pop(step_id, {})
        return result.get("answers") or []

    try:
        raw = await ws.receive_text()
        data = json.loads(raw)

        request = (data.get("request") or "").strip()
        model = data.get("model", "")
        task_plan_id = data.get("task_plan_id", "")
        input_values = data.get("input_values") or {}
        saved_plan = data.get("saved_plan")  # Pre-existing plan steps to execute directly
        auto_run = data.get("auto_run", True)

        if not request and not saved_plan:
            await ws_send({"type": "error", "text": "Request is required"})
            return

        # Load available tools for planning
        available_tools = [
            t for t in get_all("tools", order_by="sort_index")
            if t.get("is_enabled") and t.get("type") in (0, 1, 3)  # LLM, Endpoint, Agent only
        ]

        planning_cost = None

        # Phase 1: Planning
        if saved_plan:
            plan = {"goal": request, "steps": saved_plan}
            for step in plan["steps"]:
                step["status"] = "pending"
                step["output"] = ""
        else:
            await ws_send({"type": "status", "text": "Planning execution..."})
            plan, planning_cost = await generate_plan(request, model, available_tools, input_values)

        if not plan.get("steps"):
            await ws_send({"type": "error", "text": "Failed to generate execution plan"})
            return

        # Enrich tool steps with tool name and image BEFORE sending plan to frontend
        tools_by_id = {t["id"]: t for t in available_tools}
        for step in plan.get("steps", []):
            if step.get("type") == "tool" and step.get("tool_id"):
                t = tools_by_id.get(step["tool_id"])
                if t:
                    step["tool_name"] = t.get("name", "")
                    step["tool_image"] = t.get("image_url", "")
                    step["tool_model"] = t.get("model", "")
                else:
                    step.setdefault("tool_name", step.get("tool_id", "Unknown"))

        # Send plan to frontend (now enriched with tool info)
        if saved_plan:
            await ws_send({"type": "plan", "plan": plan})
        else:
            await ws_send({"type": "plan", "plan": plan, "planning_cost": planning_cost})

        # If not auto_run, wait for user approval of the plan
        if not auto_run:
            await ws_send({"type": "awaiting_approval"})

            # Wait for approval or step-by-step instructions
            while not plan_approved.is_set():
                try:
                    msg_raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                    msg = json.loads(msg_raw)
                    action = msg.get("action", "")
                    if action == "approve":
                        plan_approved.set()
                    elif action == "skip_step":
                        sid = msg.get("step_id", "")
                        if sid:
                            skip_steps.add(sid)
                            # Mark step as skipped in plan
                            for s in plan.get("steps", []):
                                if s["id"] == sid:
                                    s["status"] = "skipped"
                            await ws_send({"type": "step_skipped", "step_id": sid})
                    elif action == "unskip_step":
                        sid = msg.get("step_id", "")
                        if sid:
                            skip_steps.discard(sid)
                            for s in plan.get("steps", []):
                                if s["id"] == sid:
                                    s["status"] = "pending"
                            await ws_send({"type": "step_unskipped", "step_id": sid})
                    elif action == "set_step_model":
                        sid = msg.get("step_id", "")
                        new_model = msg.get("model", "")
                        if sid and new_model:
                            for s in plan.get("steps", []):
                                if s["id"] == sid:
                                    s["model"] = new_model
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    return

        # Create run record
        run_id = get_uid()
        now = now_iso()

        # Resolve task name for tracking
        task_name = request[:80] if request else "Task"
        if task_plan_id:
            tp = get_by_id("task_plans", task_plan_id)
            if tp and tp.get("name"):
                task_name = tp["name"]

        run = {
            "id": run_id,
            "task_plan_id": task_plan_id,
            "request": request,
            "input_values": input_values,
            "plan": plan.get("steps", []),
            "status": STATUS_PENDING,
            "output": "",
            "model": model,
            "total_cost": {},
            "created_at": now,
            "updated_at": now,
        }
        upsert("task_runs", run)

        # Register as active task
        active_task_info = {
            "task_plan_id": task_plan_id,
            "task_name": task_name,
            "request": request,
            "current_step_name": "",
            "total_steps": len(plan.get("steps", [])),
            "created_at": now,
        }
        active_tasks[run_id] = active_task_info

        # Wrap ws_send to track current step
        original_ws_send = ws_send
        async def tracking_ws_send(msg: dict):
            if msg.get("type") == "step_start" and run_id in active_tasks:
                active_tasks[run_id]["current_step_name"] = msg.get("name", "")
            await original_ws_send(msg)

        # Phase 2: Execution — run in a task so we can receive answers concurrently
        exec_task = asyncio.create_task(
            execute_plan(run, model, tracking_ws_send, wait_for_answer, planning_cost=planning_cost)
        )
        # Store the asyncio task for cancellation support
        if run_id in active_tasks:
            active_tasks[run_id]["asyncio_task"] = exec_task

        # Listen for incoming messages (answers) while execution runs
        try:
            while not exec_task.done():
                try:
                    msg_raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                    msg = json.loads(msg_raw)
                    if msg.get("action") == "answer":
                        sid = msg.get("step_id", "")
                        if sid in pending_answers:
                            pending_answers[sid]["answers"] = msg.get("answers", [])
                            pending_answers[sid]["event"].set()
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    # Signal stop so agent loops and step iteration halt cleanly
                    stop_task(run_id)
                    exec_task.cancel()
                    return
        except Exception:
            pass

        # Wait for execution to fully complete
        try:
            run = await exec_task
        except asyncio.CancelledError:
            pass

        await ws_send({
            "type": "complete",
            "run_id": run_id,
            "output": run.get("output", "")[:5000],
            "total_cost": run.get("total_cost", {}),
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws_send({"type": "error", "text": str(e)})
        except Exception:
            pass
    finally:
        # Unregister active task and clean up stop flag
        try:
            active_tasks.pop(run_id, None)
            stop_commands.discard(run_id)
        except NameError:
            pass
        try:
            await ws.close()
        except Exception:
            pass
