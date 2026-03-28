import asyncio
import json
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, UploadFile, File, HTTPException
from database import get_all, get_by_id, upsert, delete_by_id, now_iso, get_uid
from services.template_engine import parse_text
from services.llm import chat_stream, chat_with_tools, chat_stream_with_tools
from services.agent_service import save_agent_functions, run_agent_loop
from services.pipeline_engine import _build_json_schema
from services.pipeline_engine import run_pipeline
from services.pip_utils import install_packages
from models.enums import ToolType, EndpointMethod, PipelineStatusType
from api.auth_deps import CurrentUser, get_current_user, check_permission, require_permission, check_resource_access, get_accessible_resource_ids, ws_get_current_user
import httpx
from config import TOOL_RUNS_PIPELINE_ID


# ── AI Assist ────────────────────────────────────────────────────────

AI_ASSIST_SYSTEM_PROMPT = r"""You are a tool builder for an AI orchestration platform. Given a description of what the user wants, generate a complete tool configuration by calling the `generate_tool_config` tool.

## Tool Types

### LLM (type 0)
A simple prompt-based tool. Claude receives a prompt (with template variables) and returns text.
Best for: text generation, summarization, translation, analysis, formatting — anything where Claude just needs instructions and input text.

### Endpoint (type 1)
Makes an HTTP request. URL, headers, query, and body support template variables.
Best for: calling external APIs, webhooks, fetching data from web services.
Methods: 0=GET, 1=POST, 2=PUT, 3=DELETE.
endpoint_headers, endpoint_body, endpoint_query are JSON strings of key-value pair arrays, e.g. `[{"key":"Content-Type","value":"application/json"}]`

### Agent (type 3)
The most powerful type. Claude gets Python functions as tools and runs an agentic loop.
Best for: file operations, data processing, multi-step tasks, anything requiring code execution.

## Template Variables
Use `{{VariableName}}` in prompts, URLs, headers, body. Each variable must have a matching entry in request_inputs.

## Request Input Types
0=Text, 1=Number, 2=Boolean, 3=File, 4=Date, 5=Password, 6=Select

## Environment Variables (env_variables)
Environment variables store configuration values (API keys, tokens, URLs, passwords) that are set once and reused across tool runs. They are separate from request_inputs — inputs are provided by the user each run, env_variables are configured once in the tool's settings.

### How env_variables work at runtime:
1. You declare them in the `env_variables` array with a name, description, and type (0=Text, 5=Password for secrets)
2. The user sets their values in the platform's Environment Variables settings page
3. At runtime, each env_variable is **injected as a Python module-level global** with its name — you access it directly by name in your code (e.g., `API_KEY` not `os.environ["API_KEY"]`)
4. A helper function `get_var(name)` is also available as a fallback: `get_var("API_KEY")`
5. Do NOT use `os.environ` or `dotenv` — variables are NOT system environment variables, they are platform-managed

### When to use env_variables:
- API keys and tokens (e.g., JIRA_TOKEN, GOOGLE_DRIVE_ACCESS_TOKEN)
- Service URLs (e.g., JIRA_SITE, DATABASE_URL)
- Credentials (e.g., JIRA_EMAIL, SUDO_PASSWORD)
- Any configuration that should persist across runs and not be entered each time

### Example — Jira Tool env_variables declaration:
```json
[
  {"name": "JIRA_SITE", "description": "Jira Cloud site URL (e.g. https://mysite.atlassian.net)", "type": 0},
  {"name": "JIRA_EMAIL", "description": "Email address for Jira authentication", "type": 0},
  {"name": "JIRA_TOKEN", "description": "Jira API token for authentication", "type": 5}
]
```

### Example — using env_variables in agent function code:
```python
import requests

def list_projects() -> str:
    "List all Jira projects."
    # JIRA_SITE, JIRA_EMAIL, JIRA_TOKEN are available as globals
    # (injected from env_variables before this code runs)
    if not JIRA_SITE or not JIRA_TOKEN:
        return "Error: JIRA_SITE and JIRA_TOKEN must be configured in Environment Variables"
    session = requests.Session()
    session.auth = (JIRA_EMAIL, JIRA_TOKEN)
    resp = session.get(f"{JIRA_SITE.rstrip('/')}/rest/api/3/project", timeout=30)
    if resp.status_code != 200:
        return f"Error ({resp.status_code}): {resp.text}"
    return str([p["key"] + " - " + p["name"] for p in resp.json()])
```

### Example — Google Drive env_variables:
```json
[{"name": "GOOGLE_DRIVE_ACCESS_TOKEN", "description": "OAuth2 access token for Google Drive API", "type": 5}]
```
Usage in code: `headers = {"Authorization": f"Bearer {GOOGLE_DRIVE_ACCESS_TOKEN}"}`

### Example — Endpoint tool using env_variables in headers:
For Endpoint tools (type 1), env_variables are NOT injected into code — instead, use template variables in endpoint_headers/body/query that reference request_inputs. If you need a persistent API key for an Endpoint tool, use a Password input (type 5) or consider making it an Agent tool instead.

## Agent Function Code Rules
- Put all functions in a single `function_string` per agent function entry
- Each `def` becomes a separate tool Claude can call
- Use clear docstrings (they become tool descriptions for Claude to read)
- Use type hints (str→string, int→integer, float→number, bool→boolean, list→array)
- Import third-party libraries inside function bodies, not at top level
- List third-party packages in `pip_dependencies`
- Always return strings; wrap operations in try/except
- Top-level stdlib imports (os, json, re, subprocess, etc.) are fine
- Functions run with a timeout (default 120s) — handle long operations gracefully
- Functions execute in a thread via asyncio.to_thread — they can be synchronous
- Private helper functions (prefixed with _) and module-level constants are fine

## Rules
1. Tool names should be descriptive and unique
2. At least one request_input must have `is_default: true` (usually the first)
3. Use meaningful input names that work as template variables (e.g. `Input`, `Language`, not `Input2`)
4. For Agent tools, prompt is usually just `{{Input}}` — system_prompt provides real instructions
5. Write robust agent functions: check inputs, handle errors, return clear messages
6. For LLM tools, always provide a system_prompt that guides Claude's behavior
7. For Endpoint tools, populate endpoint_url, endpoint_method, and headers/body/query as needed
8. Any tool that connects to an external service (API, database, cloud) should declare env_variables for credentials/URLs
9. Always validate that required env_variables are set before using them — return a clear error message if missing
10. Use type 5 (Password) for env_variables that contain secrets (API keys, tokens, passwords)
"""

TOOL_CONFIG_SCHEMA = {
    "name": "generate_tool_config",
    "description": "Generate a complete tool configuration based on the user's description.",
    "input_schema": {
        "type": "object",
        "required": ["name", "type", "description", "prompt", "request_inputs"],
        "properties": {
            "name": {"type": "string", "description": "Tool display name"},
            "type": {"type": "integer", "enum": [0, 1, 3], "description": "0=LLM, 1=Endpoint, 3=Agent"},
            "description": {"type": "string", "description": "What the tool does"},
            "tag": {"type": "string", "description": "Category tag for organization"},
            "prompt": {"type": "string", "description": "Prompt template with {{Variable}} placeholders. Agent tools usually use {{Input}}"},
            "system_prompt": {"type": "string", "description": "System instructions for Claude"},
            "model": {"type": "string", "description": "Model ID, empty string = system default"},
            "endpoint_url": {"type": "string", "description": "HTTP endpoint URL with optional {{Variable}} placeholders"},
            "endpoint_method": {"type": "integer", "enum": [0, 1, 2, 3], "description": "0=GET, 1=POST, 2=PUT, 3=DELETE"},
            "endpoint_headers": {"type": "string", "description": "JSON string of [{key,value}] pairs"},
            "endpoint_body": {"type": "string", "description": "JSON string of [{key,value}] pairs"},
            "endpoint_query": {"type": "string", "description": "JSON string of [{key,value}] pairs"},
            "endpoint_timeout": {"type": "integer", "description": "Request timeout in seconds"},
            "request_inputs": {
                "type": "array",
                "description": "Input parameters the user provides. First should have is_default=true.",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "integer", "description": "0=Text,1=Number,2=Boolean,3=File,4=Date,5=Password,6=Select"},
                        "is_required": {"type": "boolean"},
                        "is_default": {"type": "boolean"},
                    },
                },
            },
            "agent_functions": {
                "type": "array",
                "description": "Python function definitions for Agent tools",
                "items": {
                    "type": "object",
                    "required": ["name", "function_string"],
                    "properties": {
                        "name": {"type": "string", "description": "Module name"},
                        "description": {"type": "string", "description": "What this function module does"},
                        "function_string": {"type": "string", "description": "Complete Python source code with def statements"},
                    },
                },
            },
            "pip_dependencies": {
                "type": "array",
                "description": "Python packages to install (e.g. ['requests', 'jira', 'openpyxl>=3.1.0'])",
                "items": {"type": "string"},
            },
            "env_variables": {
                "type": "array",
                "description": "Environment variables for persistent configuration (API keys, URLs, tokens). Values are set by the user in settings, injected as module globals at runtime.",
                "items": {
                    "type": "object",
                    "required": ["name", "description", "type"],
                    "properties": {
                        "name": {"type": "string", "description": "Variable name, UPPER_SNAKE_CASE (e.g. JIRA_TOKEN, API_KEY)"},
                        "description": {"type": "string", "description": "What this variable is for and example values"},
                        "type": {"type": "integer", "enum": [0, 5], "description": "0=Text (visible), 5=Password (hidden, for secrets)"},
                    },
                },
            },
            "response_structure": {
                "type": "array",
                "description": "Expected output fields for structured JSON responses",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "type": {"type": "string", "enum": ["string", "number", "boolean", "object"]},
                        "children": {"type": "array"},
                    },
                },
            },
        },
    },
}


def _build_ai_assist_message(description: str, current_tool: dict) -> str:
    """Build a user message with the description and current tool context."""
    parts = [f"## User Request\n{description}\n"]

    # Include current tool state so AI can build upon it
    ctx = []
    if current_tool.get("name"):
        ctx.append(f"Name: {current_tool['name']}")
    tool_type = current_tool.get("type")
    if tool_type is not None:
        type_names = {0: "LLM", 1: "Endpoint", 3: "Agent"}
        ctx.append(f"Type: {type_names.get(tool_type, str(tool_type))}")
    if current_tool.get("tag"):
        ctx.append(f"Tag: {current_tool['tag']}")
    if current_tool.get("description"):
        ctx.append(f"Description: {current_tool['description']}")
    if current_tool.get("prompt"):
        ctx.append(f"Prompt: {current_tool['prompt']}")
    if current_tool.get("system_prompt"):
        ctx.append(f"System Prompt: {current_tool['system_prompt']}")
    if current_tool.get("endpoint_url"):
        ctx.append(f"Endpoint URL: {current_tool['endpoint_url']}")
    if current_tool.get("endpoint_method") is not None:
        method_names = {0: "GET", 1: "POST", 2: "PUT", 3: "DELETE"}
        ctx.append(f"Endpoint Method: {method_names.get(current_tool['endpoint_method'], str(current_tool['endpoint_method']))}")
    if current_tool.get("endpoint_headers"):
        ctx.append(f"Endpoint Headers: {current_tool['endpoint_headers']}")
    if current_tool.get("endpoint_body"):
        ctx.append(f"Endpoint Body: {current_tool['endpoint_body']}")
    if current_tool.get("endpoint_query"):
        ctx.append(f"Endpoint Query: {current_tool['endpoint_query']}")
    inputs = current_tool.get("request_inputs") or []
    if inputs:
        input_details = []
        for i in inputs:
            name = i.get("name", "")
            if not name:
                continue
            type_names_map = {0: "Text", 1: "Number", 2: "Boolean", 3: "File", 4: "Date", 5: "Password", 6: "Select"}
            itype = type_names_map.get(i.get("type", 0), "Text")
            req = "required" if i.get("is_required") else "optional"
            default = ", default" if i.get("is_default") else ""
            desc = f' — {i["description"]}' if i.get("description") else ""
            input_details.append(f"  - {name} ({itype}, {req}{default}){desc}")
        if input_details:
            ctx.append("Current Inputs:\n" + "\n".join(input_details))
    env_vars = current_tool.get("env_variables") or []
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
    pip_deps = current_tool.get("pip_dependencies") or []
    if pip_deps:
        ctx.append(f"Pip Dependencies: {', '.join(pip_deps)}")
    fns = current_tool.get("agent_functions") or []
    if fns:
        fn_details = []
        for f in fns:
            if f.get("is_deleted"):
                continue
            fname = f.get("name", "")
            fdesc = f.get("description", "")
            fcode = f.get("function_string", "")
            if fname:
                fn_details.append(f"  - {fname}: {fdesc} ({len(fcode)} chars of code)")
        if fn_details:
            ctx.append("Agent Functions:\n" + "\n".join(fn_details))

    if ctx:
        parts.append("## Current Tool State\n" + "\n".join(ctx))

    parts.append("\nGenerate the complete tool configuration by calling `generate_tool_config`.")
    return "\n\n".join(parts)


router = APIRouter()


@router.get("")
async def list_tools(user: CurrentUser = Depends(get_current_user)):
    accessible_ids = get_accessible_resource_ids(user, "tools")
    all_tools = get_all("tools", order_by="sort_index")
    if accessible_ids is None:  # admin
        return all_tools
    return [t for t in all_tools if t["id"] in accessible_ids]


@router.get("/{tool_id}")
async def get_tool(tool_id: str):
    tool = get_by_id("tools", tool_id)
    if not tool:
        return {"error": "not found"}
    return tool


@router.post("")
async def save_tool(tool: dict, user: CurrentUser = Depends(get_current_user)):
    existing = get_by_id("tools", tool.get("id", ""))
    action = "edit" if existing else "create"
    if not check_permission(user, "tools", action):
        from fastapi import HTTPException
        raise HTTPException(403, "Permission denied")
    tool["updated_at"] = now_iso()
    # Save agent functions to disk if Agent type
    if tool.get("type") == ToolType.Agent:
        save_agent_functions(
            tool.get("name", ""),
            tool.get("id", ""),
            tool.get("agent_functions", []),
        )
    result = upsert("tools", tool)

    # Install pip dependencies (skip already-installed packages)
    pip_results = install_packages(tool.get("pip_dependencies", []))

    # Sync env variable schema to DB
    from services.custom_var_service import sync_var_schema
    sync_var_schema("tool", result["id"], tool.get("env_variables", []))

    resp: dict = {"response": result["id"]}
    if pip_results:
        resp["pip_results"] = pip_results
    return resp


@router.post("/ai-assist")
async def ai_assist(body: dict):
    """Use AI to generate a tool configuration from a natural language description."""
    description = (body.get("description") or "").strip()
    if not description:
        return {"error": "Description is required"}

    model = body.get("model", "")
    current_tool = body.get("current_tool", {})

    user_message = _build_ai_assist_message(description, current_tool)
    messages = [{"role": "user", "content": user_message}]

    try:
        result = await chat_with_tools(
            messages,
            [TOOL_CONFIG_SCHEMA],
            model,
            AI_ASSIST_SYSTEM_PROMPT,
            tool_choice={"type": "tool", "name": "generate_tool_config"},
        )

        # Extract the tool_use block
        for block in result.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "generate_tool_config":
                return {
                    "tool_config": block.get("input", {}),
                    "usage": result.get("usage", {}),
                }

        return {"error": "AI did not return a tool configuration"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/{tool_id}/image")
async def upload_tool_image(tool_id: str, file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    """Upload an image for a tool. Resizes to 200x200 and stores in Azure Blob Storage."""
    if not check_permission(user, "tools", "edit"):
        raise HTTPException(403, "Permission denied")

    tool = get_by_id("tools", tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    from config import AZURE_STORAGE_CONNECTION_STRING
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise HTTPException(400, "AZURE_STORAGE_CONNECTION_STRING is not configured")

    # Validate file
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "Image must be under 10MB")

    from services.blob_service import resize_and_upload, delete_blob

    # Delete old image if exists
    old_url = tool.get("image_url", "")
    if old_url:
        delete_blob(old_url)

    # Upload new image
    image_url = resize_and_upload(file_bytes, file.filename or "image.png")

    # Update tool record
    tool["image_url"] = image_url
    tool["updated_at"] = now_iso()
    upsert("tools", tool)

    return {"image_url": image_url}


@router.delete("/{tool_id}/image")
async def delete_tool_image(tool_id: str, user: CurrentUser = Depends(get_current_user)):
    """Remove the image from a tool and delete the blob."""
    if not check_permission(user, "tools", "edit"):
        raise HTTPException(403, "Permission denied")

    tool = get_by_id("tools", tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    old_url = tool.get("image_url", "")
    if old_url:
        from services.blob_service import delete_blob
        delete_blob(old_url)

    tool["image_url"] = ""
    tool["updated_at"] = now_iso()
    upsert("tools", tool)

    return {"response": "ok"}


@router.delete("/{tool_id}")
async def delete_tool(tool_id: str, user: CurrentUser = Depends(require_permission("tools", "delete"))):
    from services.custom_var_service import delete_vars_for_resource
    # Clean up blob image if exists
    tool = get_by_id("tools", tool_id)
    if tool and tool.get("image_url"):
        from services.blob_service import delete_blob
        delete_blob(tool["image_url"])
    delete_vars_for_resource("tool", tool_id)
    delete_by_id("tools", tool_id)
    return {"response": "ok"}


@router.post("/mcp-test")
async def test_mcp_connection(config: dict):
    """Test an MCP server connection and return its available tools."""
    from services.mcp_client import connect_mcp, list_mcp_tools
    from services.custom_var_service import get_vars_for_resource
    from services.template_engine import parse_text as _pt

    # Resolve header templates from env vars
    tool_id = config.pop("tool_id", "")
    raw_headers = config.get("headers") or []
    if raw_headers and tool_id:
        custom_vars = get_vars_for_resource("tool", tool_id)
        var_props = [{"name": k, "value": v} for k, v in custom_vars.items()]
        resolved = {}
        for pair in raw_headers:
            if isinstance(pair, dict) and pair.get("key"):
                resolved[pair["key"]] = _pt(pair.get("value", ""), var_props)
        config["resolved_headers"] = resolved

    try:
        async with connect_mcp(config) as session:
            tools = await list_mcp_tools(session)
            return {"success": True, "tools": tools}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/shared-functions")
async def get_shared_functions():
    import os
    from config import AGENTS_DIR
    shared_dir = os.path.join(AGENTS_DIR, "Shared")
    funcs = []
    if os.path.isdir(shared_dir):
        for fname in os.listdir(shared_dir):
            if fname.endswith(".py"):
                path = os.path.join(shared_dir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                funcs.append({"name": fname, "path": path, "content": content})
    return {"response": funcs}


@router.post("/{tool_id}/run")
async def run_tool(tool_id: str, body: dict, user: CurrentUser = Depends(get_current_user)):
    """Run a tool standalone as a synthetic single-step pipeline run."""
    if not check_resource_access(user, "tools", tool_id):
        from fastapi import HTTPException
        raise HTTPException(403, "Permission denied")
    tool = get_by_id("tools", tool_id)
    if not tool:
        return {"error": "tool not found"}

    inputs = body.get("inputs", [])
    inputs_by_name = {i.get("name"): i.get("value", "") for i in inputs}

    # Populate the tool's request_inputs with the user-provided values
    # so the pipeline engine can resolve prompt templates like {{Input}}
    import copy
    tool = copy.deepcopy(tool)
    for ri in tool.get("request_inputs", []):
        name = ri.get("name", "")
        if name in inputs_by_name:
            ri["value"] = inputs_by_name[name]

    # Build a Start step
    start_id = get_uid()
    tool_step_id = get_uid()

    start_step = {
        "id": start_id,
        "name": "Start",
        "tool_id": "",
        "tool": {"type": ToolType.Start},
        "inputs": [],
        "outputs": [],
        "status": PipelineStatusType.Pending,
        "status_text": "",
        "call_cost": [],
        "tool_outputs": [],
        "next_steps": [tool_step_id],
        "next_steps_true": [],
        "next_steps_false": [],
        "is_start": True,
        "disabled": False,
        "pre_process": "",
        "post_process": "",
        "pos_x": 0,
        "pos_y": 0,
    }

    # Build the tool step
    tool_step = {
        "id": tool_step_id,
        "name": tool.get("name", "Tool"),
        "tool_id": tool_id,
        "tool": tool,
        "inputs": [{"name": "Input", "value": "", "is_required": False, "locked": True, "type": 0, "is_default": True}],
        "outputs": [],
        "status": PipelineStatusType.Pending,
        "status_text": "",
        "call_cost": [],
        "tool_outputs": [],
        "next_steps": [],
        "next_steps_true": [],
        "next_steps_false": [],
        "is_start": False,
        "disabled": False,
        "pre_process": "",
        "post_process": "",
        "pos_x": 200,
        "pos_y": 0,
    }

    # Build the synthetic pipeline snapshot
    pipeline_snapshot = {
        "id": TOOL_RUNS_PIPELINE_ID,
        "name": tool.get("name", "Tool Run"),
        "steps": [start_step, tool_step],
        "inputs": inputs,
        "edges": [{"id": get_uid(), "source": start_id, "target": tool_step_id, "source_handle": "", "target_handle": ""}],
    }

    run_id = get_uid()
    pl_run = {
        "id": run_id,
        "pipeline_id": TOOL_RUNS_PIPELINE_ID,
        "tool_id": tool_id,
        "pipeline_snapshot": pipeline_snapshot,
        "steps": [start_step, tool_step],
        "inputs": inputs,
        "outputs": [],
        "status": PipelineStatusType.Running,
        "current_step": 0,
        "guidance": "",
        "created_at": now_iso(),
        "user_id": user.id,
    }

    upsert("pipeline_runs", pl_run)
    asyncio.create_task(run_pipeline(run_id))
    return pl_run


@router.get("/{tool_id}/runs")
async def list_tool_runs(tool_id: str):
    return get_all("pipeline_runs", "tool_id = ?", (tool_id,), order_by="created_at DESC")


@router.delete("/runs/{run_id}")
async def delete_tool_run(run_id: str):
    delete_by_id("pipeline_runs", run_id)
    return {"response": "ok"}


async def ws_tool_test(ws: WebSocket):
    try:
        user = await ws_get_current_user(ws)
    except Exception:
        return
    await ws.accept()
    try:
        raw = await ws.receive_text()
        data = json.loads(raw)
        tool = data.get("tool", {})

        tool_type = tool.get("type", ToolType.LLM)
        model = tool.get("model", "")
        system_prompt = tool.get("system_prompt", "")
        request_inputs = tool.get("request_inputs", [])

        if tool_type == ToolType.LLM:
            prompt = parse_text(tool.get("prompt", ""), request_inputs)
            response_structure = tool.get("response_structure", [])
            # If chatbot_id is set, do RAG query
            chatbot_id = tool.get("chatbot_id", "")
            rag_system = system_prompt
            if chatbot_id:
                try:
                    from services.rag_service import query_index
                except ImportError:
                    query_index = None
                if query_index:
                    results = await asyncio.to_thread(query_index, chatbot_id, prompt)
                else:
                    results = []
                context = "\n\n".join([r["text"] for r in results])
                sources = list(set(r["source"] for r in results if r.get("source")))
                rag_system = f"{system_prompt}\n\nUse the following context to answer:\n\n{context}" if context else system_prompt
                if sources:
                    await ws.send_text(json.dumps({"type": "sources", "sources": sources}))

            if response_structure:
                # Structured output via forced tool_use
                schema = _build_json_schema(response_structure)
                struct_tool = {
                    "name": "structured_output",
                    "description": "Return the response in the required structured format.",
                    "input_schema": schema,
                }
                result = await chat_with_tools(
                    [{"role": "user", "content": prompt}], [struct_tool], model, rag_system,
                    tool_choice={"type": "tool", "name": "structured_output"},
                )
                for block in result.get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "structured_output":
                        await ws.send_text(json.dumps({"type": "text", "text": json.dumps(block.get("input", {}), indent=2)}))
                        break
                usage = result.get("usage", {})
                await ws.send_text(json.dumps({
                    "type": "usage",
                    "model": usage.get("model", ""),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }))
            else:
                async for chunk in chat_stream([{"role": "user", "content": prompt}], model, rag_system):
                    await ws.send_text(json.dumps(chunk))

        elif tool_type == ToolType.Endpoint:
            endpoint = parse_text(tool.get("endpoint_url", ""), request_inputs)
            method = tool.get("endpoint_method", EndpointMethod.GET)

            from services.pipeline_engine import _kv_to_dict
            props_chain = [request_inputs]
            query_dict = _kv_to_dict(tool.get("endpoint_query", []), props_chain)
            headers = _kv_to_dict(tool.get("endpoint_headers", ""), props_chain)
            body = _kv_to_dict(tool.get("endpoint_body", ""), props_chain)

            ep_timeout = tool.get("endpoint_timeout", 60) or 60
            async with httpx.AsyncClient(timeout=ep_timeout) as http:
                if method == EndpointMethod.GET:
                    resp = await http.get(endpoint, headers=headers, params=query_dict)
                elif method == EndpointMethod.POST:
                    resp = await http.post(endpoint, headers=headers, params=query_dict, json=body)
                elif method == EndpointMethod.PUT:
                    resp = await http.put(endpoint, headers=headers, params=query_dict, json=body)
                elif method == EndpointMethod.DELETE:
                    resp = await http.delete(endpoint, headers=headers, params=query_dict)
                else:
                    resp = await http.get(endpoint, headers=headers, params=query_dict)

            await ws.send_text(json.dumps({"type": "text", "text": resp.text}))

        elif tool_type == ToolType.Agent:
            prompt = parse_text(tool.get("prompt", ""), request_inputs)
            agent_text = ""
            async for chunk in run_agent_loop(
                prompt, tool.get("name", ""), tool.get("id", ""), model, system_prompt,
                mcp_servers=tool.get("mcp_servers", []),
            ):
                await ws.send_text(json.dumps(chunk))
                if chunk.get("type") == "text":
                    agent_text += chunk["text"]

            # Structured output post-formatting for agents
            response_structure = tool.get("response_structure", [])
            if response_structure and agent_text:
                schema = _build_json_schema(response_structure)
                struct_tool = {
                    "name": "structured_output",
                    "description": "Format the agent's response into the required structure.",
                    "input_schema": schema,
                }
                format_msg = [{"role": "user", "content": f"Format the following data into the required structure:\n\n{agent_text}"}]
                result = await chat_with_tools(
                    format_msg, [struct_tool], model, "",
                    tool_choice={"type": "tool", "name": "structured_output"},
                )
                for block in result.get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "structured_output":
                        await ws.send_text(json.dumps({"type": "text", "text": "\n\n--- Structured Output ---\n" + json.dumps(block.get("input", {}), indent=2)}))
                        break
                usage = result.get("usage", {})
                await ws.send_text(json.dumps({
                    "type": "usage",
                    "model": usage.get("model", ""),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }))

        else:
            await ws.send_text(json.dumps({"type": "text", "text": f"Tool type {tool_type} executed"}))

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


async def ws_ai_assist(ws: WebSocket):
    """WebSocket handler for AI-assisted tool generation with streaming progress."""
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
        current_tool = data.get("current_tool", {})

        # Status: starting
        await ws.send_text(json.dumps({"type": "status", "text": "Analyzing your description..."}))

        user_message = _build_ai_assist_message(description, current_tool)
        messages = [{"role": "user", "content": user_message}]

        tool_config = None
        async for event in chat_stream_with_tools(
            messages,
            [TOOL_CONFIG_SCHEMA],
            model,
            AI_ASSIST_SYSTEM_PROMPT,
            tool_choice={"type": "tool", "name": "generate_tool_config"},
        ):
            if event["type"] == "tool_start":
                await ws.send_text(json.dumps({"type": "status", "text": "Generating tool configuration..."}))
            elif event["type"] == "input_delta":
                await ws.send_text(json.dumps({"type": "delta", "text": event["partial_json"]}))
            elif event["type"] == "tool_done":
                tool_config = event.get("input", {})
            elif event["type"] == "usage":
                await ws.send_text(json.dumps({
                    "type": "result",
                    "tool_config": tool_config,
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
