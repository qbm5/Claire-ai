"""
Trigger service - cron scheduling, file watching, RSS polling, code execution, pipeline firing.
"""

import json
import os
import subprocess
import sys
import asyncio
import copy
import fnmatch
import hashlib
import importlib.util
import threading
import time
import traceback
from datetime import datetime, timezone

from config import TRIGGERS_DIR
from database import get_by_id, get_all, upsert, get_uid, now_iso
from services.template_engine import parse_text
from services.pipeline_engine import run_pipeline
from models.enums import TriggerType, PipelineStatusType


# ── Code save/load ───────────────────────────────────────────────────

def _trigger_dir(name: str, trigger_id: str) -> str:
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
    return os.path.join(TRIGGERS_DIR, f"{safe_name}_{trigger_id}")


def save_trigger_code(name: str, trigger_id: str, code: str):
    """Save trigger code to data/triggers/{name}_{id}/on_trigger.py"""
    if not code or not code.strip():
        return
    tdir = _trigger_dir(name, trigger_id)
    os.makedirs(tdir, exist_ok=True)
    path = os.path.join(tdir, "on_trigger.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
        if not code.endswith("\n"):
            f.write("\n")


def load_trigger_function(name: str, trigger_id: str):
    """Dynamically load the on_trigger function. Returns callable or None."""
    tdir = _trigger_dir(name, trigger_id)
    path = os.path.join(tdir, "on_trigger.py")
    if not os.path.isfile(path):
        return None

    module_name = f"trigger_{trigger_id}_on_trigger"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    # Inject scoped custom variables as module globals before execution
    from services.custom_var_service import get_vars_for_resource
    custom_vars = get_vars_for_resource("trigger", trigger_id)
    for var_name, var_value in custom_vars.items():
        setattr(module, var_name, var_value)
    setattr(module, 'get_var', lambda vname, _cv=custom_vars: _cv.get(vname, ""))

    # Build sandboxed os module BEFORE exec so `import os` inside code is intercepted
    from services.agent_service import _make_sandboxed_os_module, _install_sandboxed_import
    sandboxed_os = _make_sandboxed_os_module(custom_vars)
    _install_sandboxed_import(module, sandboxed_os)

    spec.loader.exec_module(module)

    # Post-exec: patch any already-resolved os references
    if hasattr(module, 'os') and module.os is not sandboxed_os:
        module.os = sandboxed_os
    for attr_name in dir(module):
        obj = getattr(module, attr_name, None)
        if obj is os.environ:
            setattr(module, attr_name, sandboxed_os.environ)
        elif obj is os.getenv:
            setattr(module, attr_name, sandboxed_os.getenv)

    # In Safe Mode, sandbox filesystem access to a workspace directory
    from config import TOOL_SAFE_MODE, TRIGGERS_DIR
    if TOOL_SAFE_MODE:
        from services.agent_service import _sandbox_filesystem
        trigger_dir = os.path.join(TRIGGERS_DIR, trigger_id)
        workspace = os.path.join(trigger_dir, "workspace")
        _sandbox_filesystem(module, workspace)

    fn = getattr(module, "on_trigger", None)
    return fn


# ── Trigger execution ────────────────────────────────────────────────

async def fire_trigger(trigger_id: str, event_context: dict | None = None, skip_code: bool = False) -> dict:
    """Fire a trigger: build context, run code, launch connected pipelines.

    Args:
        skip_code: If True, skip on_trigger code execution and use event_context
                   directly as outputs. Used by Custom triggers where the subprocess
                   IS the code.
    """
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return {"error": "trigger not found"}

    trigger_type = trigger.get("trigger_type", TriggerType.Cron)
    now = datetime.now(timezone.utc)

    # Build context based on trigger type (defaults)
    context = {
        "trigger_type": trigger_type,
        "trigger_name": trigger.get("name", ""),
        "trigger_time": now.isoformat(),
    }

    if trigger_type == TriggerType.FileWatcher:
        context.update({
            "file_path": "",
            "file_name": "",
            "event_type": "",
        })
    elif trigger_type == TriggerType.RSS:
        context.update({
            "feed_url": trigger.get("rss_url", ""),
            "entry_title": "",
            "entry_link": "",
            "entry_summary": "",
            "entry_id": "",
            "entry_published": "",
        })
    elif trigger_type == TriggerType.Webhook:
        context.update({
            "webhook_body": "",
            "webhook_method": "",
            "webhook_content_type": "",
            "webhook_headers": "",
        })

    # Merge real event data on top of defaults
    if event_context:
        context.update(event_context)

    # Run custom code if present (skip for Custom triggers — subprocess IS the code)
    outputs = context
    if not skip_code:
        code = trigger.get("code", "")
        if code and code.strip():
            try:
                fn = load_trigger_function(trigger.get("name", ""), trigger_id)
                if fn:
                    result = fn(context)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if isinstance(result, dict):
                        outputs = result
                    else:
                        outputs = {**context, "result": str(result)}
            except Exception as e:
                error_msg = f"Code error: {e}\n{traceback.format_exc()}"
                upsert("triggers", {
                    "id": trigger_id,
                    "last_fired_at": now.isoformat(),
                    "last_status": f"Error: {e}",
                    "fire_count": trigger.get("fire_count", 0) + 1,
                })
                return {"error": error_msg}

    # Convert outputs to Property-style list for parse_text
    output_props = [{"name": k, "value": str(v)} for k, v in outputs.items()]

    # Fire connected pipelines
    connections = trigger.get("connections", [])
    pipeline_results = []

    for conn in connections:
        if not conn.get("is_enabled", True):
            continue

        pipeline_id = conn.get("pipeline_id", "")
        if not pipeline_id:
            continue

        pipeline = get_by_id("pipelines", pipeline_id)
        if not pipeline:
            pipeline_results.append({"pipeline_id": pipeline_id, "error": "pipeline not found"})
            continue

        # Resolve input mappings
        inputs = []
        for mapping in conn.get("input_mappings", []):
            pipeline_input = mapping.get("pipeline_input", "")
            expression = mapping.get("expression", "")
            resolved = parse_text(expression, output_props)
            inputs.append({"name": pipeline_input, "value": resolved})

        # Create pipeline run
        steps = copy.deepcopy(pipeline.get("steps", []))

        run_id = get_uid()
        pl_run = {
            "id": run_id,
            "pipeline_id": pipeline_id,
            "pipeline_snapshot": pipeline,
            "steps": steps,
            "inputs": inputs,
            "outputs": [],
            "status": PipelineStatusType.Running,
            "current_step": 0,
            "guidance": pipeline.get("guidance", ""),
            "created_at": now_iso(),
            "user_id": "system",
        }
        upsert("pipeline_runs", pl_run)
        asyncio.create_task(run_pipeline(run_id))
        pipeline_results.append({"pipeline_id": pipeline_id, "run_id": run_id})

    # Update trigger status
    upsert("triggers", {
        "id": trigger_id,
        "last_fired_at": now.isoformat(),
        "last_status": "OK",
        "fire_count": trigger.get("fire_count", 0) + 1,
    })

    return {"status": "fired", "outputs": outputs, "pipelines": pipeline_results}


# ── Scheduler / loop management ──────────────────────────────────────

_scheduler_tasks: dict[str, asyncio.Task] = {}
_watcher_observers: dict = {}   # trigger_id -> watchdog Observer
_rss_seen: dict[str, set] = {}  # trigger_id -> set of seen entry keys
_custom_processes: dict[str, subprocess.Popen] = {}  # trigger_id -> subprocess


# ── Cron loop ────────────────────────────────────────────────────────

async def _cron_loop(trigger_id: str, cron_expr: str):
    """Async loop: compute next fire time, sleep, fire, repeat."""
    from croniter import croniter

    try:
        while True:
            now = datetime.now(timezone.utc)
            cron = croniter(cron_expr, now)
            next_fire = cron.get_next(datetime)
            delay = (next_fire - now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)

            # Re-check that trigger is still enabled before firing
            trigger = get_by_id("triggers", trigger_id)
            if not trigger or not trigger.get("is_enabled"):
                break

            try:
                await fire_trigger(trigger_id)
            except Exception as e:
                print(f"[Trigger {trigger_id}] fire error: {e}")

    except asyncio.CancelledError:
        pass


# ── File Watcher loop ────────────────────────────────────────────────

async def _file_watcher_loop(trigger_id: str):
    """Watch a directory for file changes using watchdog."""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return

    watch_path = trigger.get("watch_path", "")
    if not watch_path or not os.path.isdir(watch_path):
        print(f"[Trigger {trigger_id}] watch_path not found: {watch_path}")
        return

    watch_events = trigger.get("watch_events", ["created", "modified", "deleted"])
    watch_patterns = trigger.get("watch_patterns", "")
    patterns = [p.strip() for p in watch_patterns.split(",") if p.strip()] if watch_patterns else []

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    # Debounce: track (file_path, event_type) -> last_fire_time
    debounce: dict[tuple, float] = {}
    DEBOUNCE_SECS = 2.0

    # Map watchdog event types to our names
    EVENT_MAP = {
        "created": "created",
        "modified": "modified",
        "deleted": "deleted",
        "moved": "modified",  # treat moves as modified
    }

    class Handler(FileSystemEventHandler):
        def _handle(self, event):
            if event.is_directory:
                return
            evt_type = EVENT_MAP.get(event.event_type, "")
            if not evt_type:
                return
            loop.call_soon_threadsafe(queue.put_nowait, (event.src_path, evt_type))

        def on_created(self, event):
            self._handle(event)

        def on_modified(self, event):
            self._handle(event)

        def on_deleted(self, event):
            self._handle(event)

        def on_moved(self, event):
            self._handle(event)

    observer = Observer()
    observer.schedule(Handler(), watch_path, recursive=True)
    observer.start()
    _watcher_observers[trigger_id] = observer

    try:
        while True:
            file_path, evt_type = await queue.get()

            # Re-check trigger is still enabled
            t = get_by_id("triggers", trigger_id)
            if not t or not t.get("is_enabled"):
                break

            # Re-read config for live updates
            current_events = t.get("watch_events", ["created", "modified", "deleted"])
            current_patterns_str = t.get("watch_patterns", "")
            current_patterns = [p.strip() for p in current_patterns_str.split(",") if p.strip()] if current_patterns_str else []

            # Filter by event type
            if evt_type not in current_events:
                continue

            # Filter by glob patterns
            file_name = os.path.basename(file_path)
            if current_patterns and not any(fnmatch.fnmatch(file_name, p) for p in current_patterns):
                continue

            # Debounce
            key = (file_path, evt_type)
            now = time.monotonic()
            if key in debounce and (now - debounce[key]) < DEBOUNCE_SECS:
                continue
            debounce[key] = now

            try:
                await fire_trigger(trigger_id, event_context={
                    "file_path": file_path,
                    "file_name": file_name,
                    "event_type": evt_type,
                })
            except Exception as e:
                print(f"[Trigger {trigger_id}] fire error: {e}")

    except asyncio.CancelledError:
        pass
    finally:
        observer.stop()
        observer.join(timeout=5)
        _watcher_observers.pop(trigger_id, None)


# ── RSS poll loop ────────────────────────────────────────────────────

def _entry_key(entry) -> str:
    """Derive a unique key for an RSS entry."""
    entry_id = getattr(entry, "id", "") or ""
    if entry_id:
        return entry_id
    link = getattr(entry, "link", "") or ""
    if link:
        return link
    title = getattr(entry, "title", "") or ""
    return hashlib.md5(title.encode()).hexdigest()


async def _rss_loop(trigger_id: str):
    """Poll an RSS feed periodically and fire for new entries."""
    import feedparser

    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return

    rss_url = trigger.get("rss_url", "")
    if not rss_url:
        print(f"[Trigger {trigger_id}] no rss_url configured")
        return

    poll_minutes = trigger.get("rss_poll_minutes", 15) or 15

    # Seed: fetch once and mark all current entries as seen
    try:
        feed = await asyncio.to_thread(feedparser.parse, rss_url)
        seen = {_entry_key(e) for e in feed.entries}
    except Exception as e:
        print(f"[Trigger {trigger_id}] initial RSS fetch error: {e}")
        seen = set()

    _rss_seen[trigger_id] = seen
    print(f"[Trigger {trigger_id}] RSS seeded with {len(seen)} entries from {rss_url}")

    try:
        while True:
            # Re-read config each cycle for live changes
            t = get_by_id("triggers", trigger_id)
            if not t or not t.get("is_enabled"):
                break

            current_url = t.get("rss_url", rss_url)
            current_poll = t.get("rss_poll_minutes", 15) or 15

            await asyncio.sleep(current_poll * 60)

            # Re-check after sleep
            t = get_by_id("triggers", trigger_id)
            if not t or not t.get("is_enabled"):
                break

            current_url = t.get("rss_url", current_url)

            try:
                feed = await asyncio.to_thread(feedparser.parse, current_url)
            except Exception as e:
                print(f"[Trigger {trigger_id}] RSS fetch error: {e}")
                continue

            for entry in feed.entries:
                key = _entry_key(entry)
                if key in seen:
                    continue
                seen.add(key)

                try:
                    await fire_trigger(trigger_id, event_context={
                        "feed_url": current_url,
                        "entry_title": getattr(entry, "title", ""),
                        "entry_link": getattr(entry, "link", ""),
                        "entry_summary": getattr(entry, "summary", ""),
                        "entry_id": getattr(entry, "id", ""),
                        "entry_published": getattr(entry, "published", ""),
                    })
                except Exception as e:
                    print(f"[Trigger {trigger_id}] fire error for entry {key}: {e}")

    except asyncio.CancelledError:
        pass
    finally:
        _rss_seen.pop(trigger_id, None)


# ── Custom trigger loop ───────────────────────────────────────────────

_MAX_LINE_SIZE = 1_000_000  # 1 MB guard

async def _custom_loop(trigger_id: str):
    """Spawn a subprocess running the user's run(emit) code, read JSON-line emits.

    Uses subprocess.Popen + a reader thread instead of asyncio.create_subprocess_exec
    for Windows compatibility (SelectorEventLoop doesn't support async subprocesses).
    """
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return

    tdir = _trigger_dir(trigger.get("name", ""), trigger_id)
    module_path = os.path.join(tdir, "on_trigger.py")

    if not os.path.isfile(module_path):
        upsert("triggers", {
            "id": trigger_id,
            "last_status": "Error: no code file found",
        })
        print(f"[Trigger {trigger_id}] Custom: no code file at {module_path}")
        return

    runner_path = os.path.join(os.path.dirname(__file__), "trigger_runner.py")
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    proc: subprocess.Popen | None = None

    def _reader_thread(p: subprocess.Popen):
        """Read stdout lines in a thread and push them into the async queue."""
        try:
            for raw_line in p.stdout:
                loop.call_soon_threadsafe(queue.put_nowait, raw_line)
        except Exception:
            pass
        # Signal EOF
        loop.call_soon_threadsafe(queue.put_nowait, None)

    try:
        # Build clean env: system essentials + trigger's own custom variables only
        from services.custom_var_service import get_vars_for_resource
        _SYS_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "USERPROFILE",
                      "APPDATA", "LOCALAPPDATA", "HOME", "LANG", "PYTHONPATH",
                      "VIRTUAL_ENV", "PYTHONHOME")
        clean_env = {k: v for k, v in os.environ.items() if k.upper() in _SYS_KEYS}
        clean_env.update(get_vars_for_resource("trigger", trigger_id))

        proc = subprocess.Popen(
            [sys.executable, runner_path, module_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_env,
            cwd=tdir,
        )
        _custom_processes[trigger_id] = proc
        print(f"[Trigger {trigger_id}] Custom subprocess started (pid={proc.pid})")

        # Start reader thread for stdout
        reader = threading.Thread(target=_reader_thread, args=(proc,), daemon=True)
        reader.start()

        # Consume lines from the queue
        while True:
            line_bytes = await queue.get()
            if line_bytes is None:
                break  # EOF — process exited

            if len(line_bytes) > _MAX_LINE_SIZE:
                print(f"[Trigger {trigger_id}] Skipping oversized line ({len(line_bytes)} bytes)")
                continue

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[Trigger {trigger_id}] Non-JSON stdout: {line[:200]}")
                continue

            msg_type = msg.get("type", "")

            if msg_type == "emit":
                data = msg.get("data", {})
                if not isinstance(data, dict):
                    data = {"value": str(data)}
                try:
                    await fire_trigger(trigger_id, event_context=data, skip_code=True)
                except Exception as e:
                    print(f"[Trigger {trigger_id}] fire error on emit: {e}")

            elif msg_type == "log":
                level = msg.get("level", "info")
                message = msg.get("message", "")
                print(f"[Trigger {trigger_id}] [{level}] {message}")

        # Process exited — collect exit code and stderr
        proc.wait()
        reader.join(timeout=5)
        stderr_text = proc.stderr.read().decode("utf-8", errors="replace").strip() if proc.stderr else ""
        exit_code = proc.returncode

        if exit_code == 0:
            status = "Subprocess exited normally"
        else:
            status = f"Error: subprocess exited with code {exit_code}"
            if stderr_text:
                status += f" — {stderr_text[:200]}"
                print(f"[Trigger {trigger_id}] stderr: {stderr_text[:500]}")

        upsert("triggers", {
            "id": trigger_id,
            "last_status": status,
        })
        print(f"[Trigger {trigger_id}] Custom subprocess ended (code={exit_code})")

    except asyncio.CancelledError:
        # Graceful shutdown: terminate, wait 5s, kill if needed
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise
    finally:
        _custom_processes.pop(trigger_id, None)


# ── Generalized start / cancel ───────────────────────────────────────

def start_trigger(trigger_id: str):
    """Start the appropriate loop for a trigger based on its type."""
    cancel_trigger(trigger_id)

    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return

    trigger_type = trigger.get("trigger_type", TriggerType.Cron)

    if trigger_type == TriggerType.Cron:
        cron_expr = trigger.get("cron_expression", "")
        if cron_expr:
            task = asyncio.create_task(_cron_loop(trigger_id, cron_expr))
            _scheduler_tasks[trigger_id] = task
    elif trigger_type == TriggerType.FileWatcher:
        task = asyncio.create_task(_file_watcher_loop(trigger_id))
        _scheduler_tasks[trigger_id] = task
    elif trigger_type == TriggerType.RSS:
        task = asyncio.create_task(_rss_loop(trigger_id))
        _scheduler_tasks[trigger_id] = task
    elif trigger_type == TriggerType.Custom:
        task = asyncio.create_task(_custom_loop(trigger_id))
        _scheduler_tasks[trigger_id] = task
    # Webhook has no loop — it's triggered via HTTP endpoint


def cancel_trigger(trigger_id: str):
    """Cancel an active loop (cron, file watcher, RSS, or custom subprocess)."""
    task = _scheduler_tasks.pop(trigger_id, None)
    if task and not task.done():
        task.cancel()

    # Also stop watchdog observer if running
    observer = _watcher_observers.pop(trigger_id, None)
    if observer:
        try:
            observer.stop()
        except Exception:
            pass

    # Kill custom subprocess if running
    proc = _custom_processes.pop(trigger_id, None)
    if proc and proc.returncode is None:
        try:
            proc.terminate()
        except Exception:
            pass


async def start_all_triggers():
    """Load all enabled triggers and start their loops. Called from lifespan."""
    triggers = get_all("triggers", "is_enabled = 1")
    count = 0
    for t in triggers:
        trigger_type = t.get("trigger_type", TriggerType.Cron)
        if trigger_type == TriggerType.Webhook:
            continue  # Webhook has no loop
        start_trigger(t["id"])
        count += 1
    if count:
        print(f"[Triggers] Started {count} trigger loop(s)")


# Backward-compat alias
start_all_schedulers = start_all_triggers
