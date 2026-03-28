import json
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from database import get_all, get_by_id, upsert, delete_by_id, now_iso
from services.trigger_service import (
    save_trigger_code, fire_trigger,
    start_trigger, cancel_trigger,
)
from services.llm import chat_stream_with_tools
from models.enums import TriggerType
from services.pip_utils import install_packages
from api.auth_deps import CurrentUser, get_current_user, check_permission, require_permission, check_resource_access, get_accessible_resource_ids, ws_get_current_user


router = APIRouter()


# ── Trigger AI Assist ────────────────────────────────────────────────

TRIGGER_AI_ASSIST_SYSTEM_PROMPT = r"""You are a trigger configuration builder for an AI orchestration platform. Given a description, generate a complete trigger configuration by calling `generate_trigger_config`.

## Trigger Types

Each trigger has a `trigger_type` field that MUST be one of these integers:

- **0 = Cron**: Fires on a cron schedule. Set `cron_expression` (e.g. "0 * * * *" = every hour, "*/5 * * * *" = every 5 min, "0 9 * * MON-FRI" = weekdays at 9am).
- **1 = FileWatcher**: Fires when files change in a **local** directory. Set `watch_path` (local filesystem path), `watch_patterns` (comma-separated globs like "*.csv,*.json"), and `watch_events` (array of "created", "modified", "deleted"). Uses the watchdog library internally — the directory must be locally accessible.
- **2 = Webhook**: Fires when an external HTTP POST hits its auto-generated endpoint URL. No special config needed — the platform creates the URL automatically. Code receives the webhook payload in context.
- **3 = RSS**: Fires when new items appear in an RSS/Atom feed. Set `rss_url` and `rss_poll_minutes`. Uses feedparser internally — seeded on first run so only NEW entries fire.
- **4 = Custom**: Long-lived Python subprocess. Uses `def run(emit):` instead of `def on_trigger(context):`. Best for: polling remote systems, watching non-local resources, custom event sources, or anything that needs a persistent loop.

## Code

### Standard triggers (types 0, 1, 2, 3) — on_trigger handler

All standard triggers use this handler signature:
```python
def on_trigger(context: dict) -> dict:
    # Process the event and return outputs
    return {"output_name": "value"}
```

The function:
- Receives a `context` dict with trigger metadata and event-specific data
- MUST return a dict — the keys become the trigger's outputs
- Runs in-process (loaded as a Python module), NOT as a subprocess
- Has access to env_variables as **module-level globals** (e.g., just use `API_KEY` directly)
- Also has `get_var("VAR_NAME")` helper available
- Do NOT use `os.environ` or `os.getenv` — env variables are platform-managed, not system env vars
- Can be synchronous or async (async will be awaited)
- Import third-party libraries inside the function body

### Custom triggers (type 4) — run subprocess

Custom triggers use a completely different execution model — they run as a **separate subprocess**:
```python
def run(emit):
    import time
    while True:
        emit({"output_name": "value"})
        time.sleep(60)
```

The function:
- Takes an `emit` callable — call `emit(dict)` to fire the trigger with output data
- Runs in a **separate Python process** (subprocess), NOT in-process
- MUST use `os.getenv("VAR_NAME")` for env variables (they are injected into the subprocess environment)
- Do NOT use `get_var()` or bare globals — those only work for in-process triggers
- Should contain a `while True:` loop that runs indefinitely
- Use `time.sleep()` between iterations to control poll frequency
- Can also be async: `async def run(emit):` with `await asyncio.sleep()`
- The subprocess is terminated gracefully when the trigger is disabled

### Available context variables (on_trigger types only):
- **All types**: `trigger_type`, `trigger_name`, `trigger_time` (ISO 8601 UTC)
- **Cron (type 0)**: Only the base context variables above
- **FileWatcher (type 1)**: `file_path` (full path), `file_name` (basename), `event_type` ("created"/"modified"/"deleted")
- **Webhook (type 2)**: `webhook_body` (JSON string of the POST body), `webhook_method`, `webhook_content_type`, `webhook_headers` (JSON string), plus `body_*` (each top-level body key is flattened as `body_keyname`)
- **RSS (type 3)**: `feed_url`, `entry_title`, `entry_link`, `entry_summary`, `entry_id`, `entry_published`

## Environment Variables (env_variables)

Environment variables store persistent configuration (API keys, tokens, URLs, credentials) that are set once and reused across trigger fires.

### How they work:
1. Declare them in the `env_variables` array with name, description, and type (0=Text, 5=Password for secrets)
2. The user sets values in the platform's Settings > Custom Variables page
3. At runtime, they are available in your code — but HOW depends on trigger type:

### CRITICAL: Different access methods by trigger type

**Standard triggers (types 0, 1, 2, 3)** — on_trigger code:
- Variables are injected as **module-level globals** before code execution
- Access directly by name: `API_KEY`, `DATABASE_URL`
- Or use helper: `get_var("API_KEY")`
- Do NOT use `os.environ` or `os.getenv` — they won't work

Example:
```python
import requests

def on_trigger(context: dict) -> dict:
    # SLACK_WEBHOOK_URL is available as a module global
    if not SLACK_WEBHOOK_URL:
        return {"error": "SLACK_WEBHOOK_URL not configured"}
    requests.post(SLACK_WEBHOOK_URL, json={"text": f"Trigger fired: {context['trigger_name']}"})
    return {"status": "notified", "time": context["trigger_time"]}
```

**Custom triggers (type 4)** — run subprocess:
- Variables are injected into the **subprocess environment**
- MUST use `os.getenv("VAR_NAME")` or `os.environ.get("VAR_NAME")`
- Module globals and `get_var()` are NOT available

Example:
```python
def run(emit):
    import os, time, requests

    api_url = os.getenv("API_URL", "")
    api_key = os.getenv("API_KEY", "")
    poll_interval = int(os.getenv("POLL_INTERVAL", "60"))

    if not api_url or not api_key:
        print("ERROR: API_URL and API_KEY must be configured")
        return

    last_id = None
    while True:
        resp = requests.get(api_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        if resp.ok:
            data = resp.json()
            if data.get("id") != last_id:
                last_id = data["id"]
                emit({"item_id": str(last_id), "item_data": str(data)})
        time.sleep(poll_interval)
```

### When to use env_variables:
- API keys, tokens, and passwords for external services
- Service URLs (base URLs, webhook endpoints, connection strings)
- Configuration values that should persist (poll intervals, thresholds, directory paths)
- Any value the user shouldn't have to enter each time

## Outputs

Define named outputs that the trigger produces. These become available as `{{ output_name }}` template variables in connection input mappings.

**Important**: Every key returned by your `on_trigger()` code (or emitted by `run(emit)`) should have a matching output declaration. This tells the platform what to expect.

Output types: 0=Text (default), 1=Number, 2=Boolean

## Connections

Connections link a trigger to pipelines. Each connection has:
- `pipeline_id`: The pipeline to run (from the available pipelines list)
- `pipeline_name`: Display name (for the UI)
- `is_enabled`: Whether this connection is active
- `input_mappings`: Array of `{pipeline_input, expression}` pairs that map trigger outputs to pipeline inputs using `{{ variable }}` syntax

Example: If your trigger outputs `{"file_path": "/data/report.csv", "event": "created"}` and the target pipeline has a "FilePath" input, your mapping would be:
`{"pipeline_input": "FilePath", "expression": "{{ file_path }}"}`

## Rules

1. Always set `trigger_type` to the correct integer (0-4)
2. Generate meaningful Python code appropriate for the trigger type
3. Define outputs that match what the code returns / emits
4. If the user mentions connecting to a pipeline, include it in connections using the provided pipeline list
5. Use descriptive names and descriptions
6. For Cron triggers, use standard 5-field cron syntax (minute hour day month weekday)
7. For FileWatcher, ensure watch_path, watch_patterns, and watch_events are all set — watch_path must be a LOCAL directory
8. For RSS, ensure rss_url and rss_poll_minutes are set
9. For Custom triggers, ALWAYS use `def run(emit):` with a loop and `os.getenv()` for env variables
10. For standard triggers (0-3), ALWAYS use `def on_trigger(context):` and access env vars as module globals
11. Include pip_dependencies for any third-party packages used in code
12. Any trigger that connects to an external service should declare env_variables for credentials/URLs
13. Always validate that required env_variables are set before using them — return/print a clear error if missing
14. Use type 5 (Password) for env_variables containing secrets (API keys, tokens, passwords, connection strings)
15. If monitoring a remote/cloud resource (Azure, AWS, GCP), use Custom (type 4) — FileWatcher only works for local directories
"""

TRIGGER_CONFIG_SCHEMA = {
    "name": "generate_trigger_config",
    "description": "Generate a complete trigger configuration.",
    "input_schema": {
        "type": "object",
        "required": ["name", "trigger_type", "description"],
        "properties": {
            "name": {"type": "string", "description": "Trigger display name"},
            "description": {"type": "string", "description": "What the trigger does"},
            "tag": {"type": "string", "description": "Category tag"},
            "trigger_type": {"type": "integer", "enum": [0, 1, 2, 3, 4], "description": "0=Cron, 1=FileWatcher, 2=Webhook, 3=RSS, 4=Custom"},
            "cron_expression": {"type": "string", "description": "Cron schedule (for type 0). 5-field format: min hour day month weekday"},
            "watch_path": {"type": "string", "description": "Directory to watch (for type 1)"},
            "watch_patterns": {"type": "string", "description": "Comma-separated file globs (for type 1), e.g. '*.csv,*.json'"},
            "watch_events": {"type": "array", "items": {"type": "string", "enum": ["created", "modified", "deleted"]}, "description": "Events to watch (for type 1)"},
            "rss_url": {"type": "string", "description": "RSS/Atom feed URL (for type 3)"},
            "rss_poll_minutes": {"type": "integer", "description": "Poll interval in minutes (for type 3)"},
            "code": {"type": "string", "description": "Python code: def on_trigger(context) or def run(emit) for Custom"},
            "outputs": {
                "type": "array",
                "description": "Named outputs the trigger produces",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "integer", "description": "0=Text, 1=Number, 2=Boolean"},
                    },
                },
            },
            "pip_dependencies": {"type": "array", "items": {"type": "string"}, "description": "Python packages to install"},
            "env_variables": {
                "type": "array",
                "description": "Environment variables the code needs",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Variable name (e.g. API_KEY)"},
                        "description": {"type": "string"},
                        "type": {"type": "integer", "description": "0=Text, 5=Secret/Password"},
                    },
                },
            },
            "connections": {
                "type": "array",
                "description": "Pipeline connections",
                "items": {
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "string"},
                        "pipeline_name": {"type": "string"},
                        "is_enabled": {"type": "boolean"},
                        "input_mappings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "pipeline_input": {"type": "string"},
                                    "expression": {"type": "string", "description": "Template expression using {{ variable }}"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _build_trigger_ai_assist_message(description: str, current_trigger: dict, available_pipelines: list) -> str:
    """Build a user message with description, current trigger state, and available pipelines."""
    parts = [f"## User Request\n{description}\n"]

    # Show available pipelines
    if available_pipelines:
        pl_lines = []
        for p in available_pipelines:
            inputs = p.get("inputs", [])
            input_names = [i.get("name", "") for i in inputs if i.get("name")]
            inp_str = f" (inputs: {', '.join(input_names)})" if input_names else ""
            pl_lines.append(f"- **{p.get('name')}** (id: `{p.get('id')}`){inp_str}")
        parts.append("## Available Pipelines\nYou can connect to these pipelines:\n" + "\n".join(pl_lines))

    # Current trigger context
    ctx = []
    if current_trigger.get("name"):
        ctx.append(f"Name: {current_trigger['name']}")
    if current_trigger.get("description"):
        ctx.append(f"Description: {current_trigger['description']}")
    tt = current_trigger.get("trigger_type")
    type_names = {0: "Cron", 1: "FileWatcher", 2: "Webhook", 3: "RSS", 4: "Custom"}
    if tt is not None:
        ctx.append(f"Type: {type_names.get(tt, str(tt))}")
    if current_trigger.get("tag"):
        ctx.append(f"Tag: {current_trigger['tag']}")

    # Type-specific fields
    if current_trigger.get("cron_expression"):
        ctx.append(f"Cron Expression: {current_trigger['cron_expression']}")
    if current_trigger.get("watch_path"):
        ctx.append(f"Watch Path: {current_trigger['watch_path']}")
    if current_trigger.get("watch_patterns"):
        ctx.append(f"Watch Patterns: {current_trigger['watch_patterns']}")
    watch_events = current_trigger.get("watch_events") or []
    if watch_events:
        ctx.append(f"Watch Events: {', '.join(watch_events)}")
    if current_trigger.get("rss_url"):
        ctx.append(f"RSS URL: {current_trigger['rss_url']}")
    if current_trigger.get("rss_poll_minutes"):
        ctx.append(f"RSS Poll Minutes: {current_trigger['rss_poll_minutes']}")

    # Code
    code = current_trigger.get("code", "")
    if code and code.strip():
        ctx.append(f"Current code:\n```python\n{code.strip()}\n```")

    # Outputs
    outputs = current_trigger.get("outputs", [])
    if outputs:
        out_details = []
        for o in outputs:
            name = o.get("name", "")
            if not name:
                continue
            otype_map = {0: "Text", 1: "Number", 2: "Boolean"}
            otype = otype_map.get(o.get("type", 0), "Text")
            out_details.append(f"  - {name} ({otype})")
        if out_details:
            ctx.append("Outputs:\n" + "\n".join(out_details))

    # Env variables
    env_vars = current_trigger.get("env_variables") or []
    if env_vars:
        env_details = []
        for v in env_vars:
            name = v.get("name", "")
            if not name:
                continue
            vtype = "Password" if v.get("type") == 5 else "Text"
            desc = f' — {v["description"]}' if v.get("description") else ""
            env_details.append(f"  - {name} ({vtype}){desc}")
        if env_details:
            ctx.append("Environment Variables:\n" + "\n".join(env_details))

    # Pip dependencies
    pip_deps = current_trigger.get("pip_dependencies") or []
    if pip_deps:
        ctx.append(f"Pip Dependencies: {', '.join(pip_deps)}")

    # Connections
    conns = current_trigger.get("connections", [])
    if conns:
        conn_details = []
        for c in conns:
            pname = c.get("pipeline_name", "")
            pid = c.get("pipeline_id", "")
            enabled = "enabled" if c.get("is_enabled") else "disabled"
            mappings = c.get("input_mappings", [])
            map_str = ", ".join(f'{m.get("pipeline_input")}={m.get("expression")}' for m in mappings) if mappings else "no mappings"
            conn_details.append(f"  - {pname} (id: {pid}, {enabled}) [{map_str}]")
        if conn_details:
            ctx.append("Connections:\n" + "\n".join(conn_details))

    if ctx:
        parts.append("## Current Trigger State\n" + "\n".join(ctx))

    parts.append("\nGenerate the complete trigger configuration by calling `generate_trigger_config`.")
    return "\n\n".join(parts)


async def ws_ai_assist_trigger(ws: WebSocket):
    """WebSocket handler for AI-assisted trigger generation with streaming progress."""
    try:
        user = await ws_get_current_user(ws)
    except Exception:
        return
    await ws.accept()
    try:
        raw = await ws.receive_text()
        data = json.loads(raw)

        description = (data.get("description") or "").strip()
        if not description:
            await ws.send_text(json.dumps({"type": "error", "text": "Description is required"}))
            return

        model = data.get("model", "")
        current_trigger = data.get("current_trigger", {})

        await ws.send_text(json.dumps({"type": "status", "text": "Analyzing your description..."}))

        # Load available pipelines for context
        available_pipelines = [
            {"id": p.get("id"), "name": p.get("name"), "inputs": p.get("inputs", [])}
            for p in get_all("pipelines", order_by="sort_index")
            if not p.get("id", "").startswith("__")
        ]

        user_message = _build_trigger_ai_assist_message(description, current_trigger, available_pipelines)
        messages = [{"role": "user", "content": user_message}]

        trigger_config = None
        async for event in chat_stream_with_tools(
            messages,
            [TRIGGER_CONFIG_SCHEMA],
            model,
            TRIGGER_AI_ASSIST_SYSTEM_PROMPT,
            tool_choice={"type": "tool", "name": "generate_trigger_config"},
        ):
            if event["type"] == "tool_start":
                await ws.send_text(json.dumps({"type": "status", "text": "Generating trigger configuration..."}))
            elif event["type"] == "input_delta":
                await ws.send_text(json.dumps({"type": "delta", "text": event["partial_json"]}))
            elif event["type"] == "tool_done":
                trigger_config = event.get("input", {})
            elif event["type"] == "usage":
                await ws.send_text(json.dumps({
                    "type": "result",
                    "trigger_config": trigger_config,
                    "usage": event,
                }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.get("")
async def list_triggers(user: CurrentUser = Depends(get_current_user)):
    accessible_ids = get_accessible_resource_ids(user, "triggers")
    all_triggers = get_all("triggers", order_by="sort_index")
    if accessible_ids is None:  # admin
        return all_triggers
    return [t for t in all_triggers if t["id"] in accessible_ids]


@router.get("/{trigger_id}")
async def get_trigger(trigger_id: str):
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return {"error": "not found"}
    return trigger


@router.post("")
async def save_trigger(trigger: dict, user: CurrentUser = Depends(get_current_user)):
    existing = get_by_id("triggers", trigger.get("id", ""))
    action = "edit" if existing else "create"
    if not check_permission(user, "triggers", action):
        raise HTTPException(403, "Permission denied")
    trigger["updated_at"] = now_iso()

    # Save code to disk if present
    code = trigger.get("code", "")
    if code and code.strip():
        save_trigger_code(
            trigger.get("name", ""),
            trigger.get("id", ""),
            code,
        )

    result = upsert("triggers", trigger)

    # Install pip dependencies (skip already-installed packages)
    pip_results = install_packages(trigger.get("pip_dependencies", []))

    # Sync env variable schema to DB
    from services.custom_var_service import sync_var_schema
    sync_var_schema("trigger", result["id"], trigger.get("env_variables", []))

    # Manage trigger loop (cron, file watcher, RSS — webhook has no loop)
    trigger_id = result["id"]
    trigger_type = trigger.get("trigger_type", TriggerType.Cron)
    is_enabled = trigger.get("is_enabled", False)

    if is_enabled and trigger_type != TriggerType.Webhook:
        start_trigger(trigger_id)
    else:
        cancel_trigger(trigger_id)

    resp: dict = {"response": result["id"]}
    if pip_results:
        resp["pip_results"] = pip_results
    return resp


@router.post("/{trigger_id}/image")
async def upload_trigger_image(trigger_id: str, file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    if not check_permission(user, "triggers", "edit"):
        raise HTTPException(403, "Permission denied")
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        raise HTTPException(404, "Trigger not found")
    from config import AZURE_STORAGE_CONNECTION_STRING
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise HTTPException(400, "AZURE_STORAGE_CONNECTION_STRING is not configured")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 10MB")
    from services.blob_service import resize_and_upload, delete_blob
    old_url = trigger.get("image_url", "")
    if old_url:
        delete_blob(old_url)
    image_url = resize_and_upload(file_bytes, file.filename or "image.png")
    trigger["image_url"] = image_url
    trigger["updated_at"] = now_iso()
    upsert("triggers", trigger)
    return {"image_url": image_url}


@router.delete("/{trigger_id}/image")
async def delete_trigger_image(trigger_id: str, user: CurrentUser = Depends(get_current_user)):
    if not check_permission(user, "triggers", "edit"):
        raise HTTPException(403, "Permission denied")
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        raise HTTPException(404, "Trigger not found")
    old_url = trigger.get("image_url", "")
    if old_url:
        from services.blob_service import delete_blob
        delete_blob(old_url)
    trigger["image_url"] = ""
    trigger["updated_at"] = now_iso()
    upsert("triggers", trigger)
    return {"response": "ok"}


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str, user: CurrentUser = Depends(require_permission("triggers", "delete"))):
    from services.custom_var_service import delete_vars_for_resource
    # Clean up blob image if exists
    trigger = get_by_id("triggers", trigger_id)
    if trigger and trigger.get("image_url"):
        from services.blob_service import delete_blob
        delete_blob(trigger["image_url"])
    cancel_trigger(trigger_id)
    delete_vars_for_resource("trigger", trigger_id)
    delete_by_id("triggers", trigger_id)
    return {"response": "ok"}


@router.post("/{trigger_id}/fire")
async def manual_fire(trigger_id: str, user: CurrentUser = Depends(get_current_user)):
    if not check_resource_access(user, "triggers", trigger_id):
        raise HTTPException(403, "Permission denied")
    result = await fire_trigger(trigger_id)
    return result


@router.post("/{trigger_id}/webhook")
async def webhook_receive(trigger_id: str, request: Request):
    """Receive an external webhook POST and fire the trigger."""
    trigger = get_by_id("triggers", trigger_id)
    if not trigger:
        return JSONResponse({"error": "trigger not found"}, status_code=404)

    if trigger.get("trigger_type") != TriggerType.Webhook:
        return JSONResponse({"error": "trigger is not a Webhook type"}, status_code=400)

    if not trigger.get("is_enabled"):
        return JSONResponse({"error": "trigger is disabled"}, status_code=400)

    # Parse body
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()

    try:
        body = json.loads(raw_body)
    except Exception:
        body = raw_body.decode("utf-8", errors="replace")

    # Build event context
    headers_dict = dict(request.headers)
    event_context = {
        "webhook_body": json.dumps(body) if isinstance(body, (dict, list)) else str(body),
        "webhook_method": request.method,
        "webhook_content_type": content_type,
        "webhook_headers": json.dumps(headers_dict),
    }

    # Flatten body keys for easy template access (body_key)
    if isinstance(body, dict):
        for k, v in body.items():
            event_context[f"body_{k}"] = str(v) if not isinstance(v, str) else v

    result = await fire_trigger(trigger_id, event_context=event_context)
    return result


