"""
Task Execution Service — AI-planned task execution.

Phase 1 (Planning): LLM analyzes user request + tool catalog → execution plan
Phase 2 (Execution): Steps execute sequentially, outputs flow forward as context
"""

import json
import time
import asyncio
import logging
import httpx

from database import get_by_id, get_all, upsert
from db.helpers import get_uid, now_iso
from config import get_model_pricing, MILLION
from services.llm import chat_with_tools, chat_complete, chat_stream
from services.agent_service import run_agent_loop, save_agent_functions, load_agent_functions
from services.template_engine import parse_text
from services.subprocess_manager import get_status as get_proc_status

logger = logging.getLogger(__name__)

# ── Status constants ─────────────────────────────────────────────

STATUS_PENDING = 0
STATUS_RUNNING = 1
STATUS_COMPLETED = 2
STATUS_FAILED = 3
STATUS_WAITING = 4

# ── Stop mechanism (mirrors pipeline_engine.stop_commands) ────────

stop_commands: set[str] = set()


def stop_task(run_id: str):
    """Signal a running task to stop."""
    stop_commands.add(run_id)


# ── Cost helpers ─────────────────────────────────────────────────

def _make_cost(model: str, input_tokens: int, output_tokens: int, detail: str = "") -> dict:
    """Create a cost entry dict."""
    pricing = get_model_pricing(model)
    input_cost = (pricing["input_cost"] / MILLION) * input_tokens
    output_cost = (pricing["output_cost"] / MILLION) * output_tokens
    return {
        "detail": detail,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
    }


def _sum_costs(costs: list[dict]) -> dict:
    """Sum a list of cost entries into a totals dict."""
    total_in = sum(c.get("input_tokens", 0) for c in costs)
    total_out = sum(c.get("output_tokens", 0) for c in costs)
    total_cost = sum(c.get("total_cost", 0) for c in costs)
    return {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "total_cost": round(total_cost, 6),
        "steps": costs,
    }


# ── Planning ─────────────────────────────────────────────────────

PLANNING_SYSTEM_PROMPT = r"""You are an AI task planner for an orchestration platform. Given a user's request and a catalog of available tools, create an execution plan by calling `generate_execution_plan`.

## Step Types

- **reasoning**: An LLM thinking/analysis/writing step. No tool needed. Use for analysis, synthesis, planning, writing, summarizing, transforming text.
- **tool**: Execute a specific saved tool from the catalog. Reference it by tool_id. Use when the task matches what the tool does.
- **ask_user**: Pause execution and ask the user clarifying questions before continuing. Use when the request is ambiguous or missing critical information that can't be inferred.

## Context & Variable System

Each step's output is stored in a context dictionary under the step's name. You can reference previous step outputs in instructions using `{{step_name}}` template syntax. This is critical for passing data between steps.

- **Step output references**: Use `{{step_name}}` where step_name is the step's `name` field. Keep step names short and snake_case for easy referencing (e.g. "download_video" not "Download the TikTok Video").
- **Endpoint response fields**: If an endpoint tool defines response fields (e.g. `path`, `duration`), those are also available as top-level context variables: `{{path}}`, `{{duration}}`.
- **User-provided inputs**: Any input values provided by the user are available as `{{input_name}}`.
- **Dot notation**: Use `{{step_name.field}}` to extract a JSON field from a step's output.

Example: If step "tts_audio" calls a TTS endpoint that returns `{"path": "/audio.wav", "duration": 5.2}`, later steps can use `{{path}}` or `{{tts_audio.path}}` in their instructions and tool_inputs.

## Tool Inputs (CRITICAL)

Each tool has named inputs listed in the catalog (e.g. "Input (required)", "Output Directory (required)"). When creating a tool step, you MUST provide values for these inputs via the `tool_inputs` object. This is how data flows into the tool.

Example tool step:
```json
{
  "type": "tool",
  "tool_id": "abc123",
  "tool_inputs": {
    "Input": "https://example.com/video",
    "Output Directory": "E:\\Temp\\Test"
  },
  "instructions": "Download the TikTok video to the output directory"
}
```

- The `tool_inputs` keys MUST match the tool's input names exactly
- Values can use `{{step_name}}` templates to reference previous step outputs
- The default "Input" is the main input — for Agent tools this becomes part of the prompt
- Non-default inputs (Output Directory, FilePath, etc.) MUST be explicitly set if the tool requires them

## Output Format (reasoning steps)

Each reasoning step has an `output_format` field that controls how the LLM formats its response. Choose carefully based on what will consume the output:

- **"raw"** — Plain text only. No markdown, no headers, no commentary. Use when the output feeds directly into a tool, API, TTS engine, file writer, or any non-human consumer. This is the most common choice.
- **"markdown"** — Formatted text with markdown allowed. Use when the output is the final deliverable for the user to read, or when the step is doing analysis/comparison that benefits from structure.
- **"json"** — Valid JSON output only. Use when the next step needs to parse structured data from this step's output.

Default is "raw". When in doubt, use "raw" — it's safer for automated pipelines.

## Rules

1. Break the request into clear, sequential steps
2. Use existing tools when they match the task — don't create reasoning steps for things tools already do
3. Use ask_user EARLY in the plan when the request is ambiguous or missing key details
4. Each step's output becomes available as context for subsequent steps
5. Keep plans focused — don't add unnecessary steps. Simpler is better.
6. **Step names MUST be short, snake_case identifiers** (e.g. "download_video", "generate_tts", "merge_output") — these are used as variable names in `{{}}` references
7. For tool steps, provide all required tool_inputs with concrete values or `{{step_name}}` references
8. If no tools match the request, use reasoning steps only — that's fine
9. For multi-part tasks, consider whether parts can be done in a single reasoning step vs needing separate steps
10. Set `output_format` on reasoning steps based on what consumes the output — "raw" for tool/API/TTS inputs, "markdown" for user-facing content, "json" for structured data
"""

PLANNING_SCHEMA = {
    "name": "generate_execution_plan",
    "description": "Generate a step-by-step execution plan for the user's request.",
    "input_schema": {
        "type": "object",
        "required": ["goal", "steps"],
        "properties": {
            "goal": {"type": "string", "description": "Brief summary of what this plan accomplishes"},
            "steps": {
                "type": "array",
                "description": "Ordered list of execution steps",
                "items": {
                    "type": "object",
                    "required": ["id", "name", "type", "instructions"],
                    "properties": {
                        "id": {"type": "string", "description": "Unique step ID (e.g. 'step_1')"},
                        "name": {"type": "string", "description": "Short display name for this step"},
                        "type": {
                            "type": "string",
                            "enum": ["reasoning", "tool", "ask_user"],
                            "description": "reasoning=LLM thinking, tool=execute a saved tool, ask_user=ask user for input",
                        },
                        "tool_id": {"type": "string", "description": "UUID of saved tool (required for type=tool)"},
                        "tool_inputs": {
                            "type": "object",
                            "description": "Key-value map of tool input values (for type=tool). Keys are the tool's input names (e.g. 'Output Directory', 'FilePath'). Values can use {{step_name}} templates.",
                            "additionalProperties": {"type": "string"},
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["raw", "markdown", "json"],
                            "description": "How the LLM should format its output. 'raw'=plain text only (for tool/API/TTS consumption), 'markdown'=formatted (for user reading), 'json'=valid JSON (for structured data). Default: raw.",
                        },
                        "instructions": {"type": "string", "description": "Detailed instructions for this step"},
                        "questions": {
                            "type": "array",
                            "description": "Questions to ask (for type=ask_user)",
                            "items": {
                                "type": "object",
                                "required": ["id", "text"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "text": {"type": "string"},
                                    "type": {"type": "string", "enum": ["text", "choice"]},
                                    "options": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _build_tool_catalog(tools: list[dict]) -> str:
    """Format available tools into a catalog string for the planner."""
    if not tools:
        return "No saved tools available. Use reasoning steps only."

    type_names = {0: "LLM", 1: "Endpoint", 3: "Agent"}
    lines = []
    for t in tools:
        tt = type_names.get(t.get("type"), str(t.get("type")))
        desc = t.get("description", "")
        inputs = t.get("request_inputs") or []
        input_str = ""
        if inputs:
            input_parts = []
            for inp in inputs:
                name = inp.get("name", "")
                req = "required" if inp.get("is_required") else "optional"
                input_parts.append(f"{name} ({req})")
            input_str = f"\n    Inputs: {', '.join(input_parts)}"

        lines.append(f"- **{t.get('name')}** (id: `{t.get('id')}`, type: {tt})\n    {desc}{input_str}")

    lines.append("")
    lines.append("**IMPORTANT**: For tool steps, the `instructions` field is the main prompt sent to the tool. "
                 "Any tool inputs listed above (especially non-default ones like 'Output Directory', 'FilePath', etc.) "
                 "MUST have their values specified clearly in the instructions or provided via `{{step_name}}` template references. "
                 "The tool cannot infer values you don't provide.")

    return "\n".join(lines)


async def generate_plan(request: str, model: str, available_tools: list[dict], input_values: dict = None) -> tuple[dict, dict]:
    """Generate an execution plan from a user request.
    Returns (plan_dict, cost_dict).
    """
    catalog = _build_tool_catalog(available_tools)

    user_msg = f"## User Request\n{request}\n\n## Available Tools\n{catalog}"
    if input_values:
        user_msg += f"\n\n## Provided Input Values\n{json.dumps(input_values, indent=2)}"
    user_msg += "\n\nGenerate an execution plan by calling `generate_execution_plan`."

    result = await chat_with_tools(
        [{"role": "user", "content": user_msg}],
        [PLANNING_SCHEMA],
        model,
        PLANNING_SYSTEM_PROMPT,
        tool_choice={"type": "tool", "name": "generate_execution_plan"},
    )

    # Extract cost from planning call
    usage = result.get("usage", {})
    plan_cost = _make_cost(
        usage.get("model", model),
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        "Planning",
    )

    for block in (result.get("content") or []):
        if block.get("type") == "tool_use" and block.get("name") == "generate_execution_plan":
            plan = block.get("input", {})
            # Ensure each step has runtime fields
            for step in plan.get("steps", []):
                step.setdefault("status", "pending")
                step.setdefault("output", "")
            return plan, plan_cost

    return {"goal": request, "steps": []}, plan_cost


# ── Execution ────────────────────────────────────────────────────

def _format_context(context: dict) -> str:
    """Format previous step outputs into a context string."""
    if not context:
        return "(No previous context)"
    parts = []
    for name, output in context.items():
        # Truncate very long outputs
        text = str(output)
        if len(text) > 8000:
            text = text[:8000] + "\n... (truncated)"
        parts.append(f"### {name}\n{text}")
    return "\n\n".join(parts)


REASONING_SYSTEM_PROMPTS = {
    "raw": (
        "You are a step in an automated execution pipeline. Your output will be consumed directly by subsequent steps "
        "(e.g. TTS engines, file writers, APIs). Output ONLY the requested content — no markdown formatting, no headers, "
        "no commentary, no preamble, no sign-off, no meta-text like 'Here is...' or 'Let me know...'. "
        "Do not wrap output in code blocks. Raw content only."
    ),
    "markdown": (
        "You are a step in an automated execution pipeline. Produce well-formatted output using markdown where appropriate. "
        "Focus on the requested content — avoid unnecessary preamble or sign-off but structure and formatting are welcome."
    ),
    "json": (
        "You are a step in an automated execution pipeline. Your output will be parsed as JSON by subsequent steps. "
        "Output ONLY valid JSON — no markdown code fences, no commentary, no explanation. Just the JSON object or array."
    ),
}


async def _execute_reasoning_step(step: dict, context: dict, model: str, ws_send) -> tuple[str, dict | None]:
    """Execute a reasoning (LLM) step. Returns (output, cost)."""
    ctx_str = _format_context(context)
    prompt = f"## Task\n{step['instructions']}\n\n## Context from previous steps\n{ctx_str}"

    output_format = step.get("output_format", "raw")
    system_prompt = REASONING_SYSTEM_PROMPTS.get(output_format, REASONING_SYSTEM_PROMPTS["raw"])

    output_parts = []
    step_cost = None
    async for chunk in chat_stream([{"role": "user", "content": prompt}], model, system_prompt):
        if chunk.get("type") == "text":
            output_parts.append(chunk["text"])
            await ws_send({"type": "step_delta", "step_id": step["id"], "text": chunk["text"]})
        elif chunk.get("type") == "usage":
            step_cost = _make_cost(
                chunk.get("model", model),
                chunk.get("input_tokens", 0),
                chunk.get("output_tokens", 0),
                step.get("name", step["id"]),
            )
    return "".join(output_parts), step_cost


def _resolve_tool_inputs(tool: dict, step: dict, context: dict) -> list[dict]:
    """Resolve a tool's request_inputs from execution context.

    Priority order for each input:
    1. Planner-provided tool_inputs (step['tool_inputs'][name])
    2. Existing template value on the input (e.g. '{{TTS.path}}')
    3. For default/Input: step instructions

    Returns a list of {name, value} dicts usable with parse_text.
    """
    import copy
    request_inputs = copy.deepcopy(tool.get("request_inputs") or [])
    planner_inputs = step.get("tool_inputs") or {}

    # Build a context props list for template resolution
    ctx_props = [{"name": k, "value": str(v)} for k, v in context.items()]

    for inp in request_inputs:
        name = inp.get("name", "")
        val = ""

        # 1. Check if planner explicitly set this input
        if name in planner_inputs:
            val = planner_inputs[name]
        else:
            # 2. Use the tool's default value (may contain templates)
            val = inp.get("value", "")

        # Resolve any template references
        if val and "{{" in val:
            val = parse_text(val, ctx_props)

        # 3. For default/Input: fall back to step instructions if still empty
        if not val.strip() and (inp.get("is_default") or name.lower() == "input"):
            val = step.get("instructions", "")

        inp["value"] = val

    return request_inputs


def _kv_resolve(raw, props: list[dict]) -> dict:
    """Resolve a KV list (body/query/headers) using a props list.

    raw: list of {key, value} dicts
    props: list of {name, value} dicts for template resolution
    """
    if not isinstance(raw, list):
        return {}
    result = {}
    for pair in raw:
        if isinstance(pair, dict) and pair.get("key"):
            val = pair.get("value", "")
            val = parse_text(val, props)
            result[pair["key"]] = val
    return result


def _parse_endpoint_response(resp_text: str, response_structure: list) -> tuple[str, dict]:
    """Parse an endpoint response using the tool's response_structure.

    Returns (formatted_output, parsed_fields_dict).
    parsed_fields_dict maps field names to values for context injection.
    """
    if not response_structure:
        return resp_text, {}

    try:
        data = json.loads(resp_text)
    except (json.JSONDecodeError, TypeError):
        return resp_text, {}

    if not isinstance(data, dict):
        return resp_text, {}

    def extract_fields(structure, source, prefix=""):
        fields = {}
        for field in structure:
            key = field.get("key", "")
            if not key:
                continue
            full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            val = source.get(key)
            if val is not None:
                children = field.get("children")
                if children and isinstance(val, dict):
                    fields.update(extract_fields(children, val, full_key))
                else:
                    fields[key] = val
        return fields

    parsed = extract_fields(response_structure, data)

    # Build a formatted output showing the fields
    lines = []
    for k, v in parsed.items():
        lines.append(f"{k}: {v}")
    formatted = "\n".join(lines) if lines else resp_text

    return formatted, parsed


async def _execute_tool_step(step: dict, context: dict, model: str, ws_send, run_id: str = "") -> tuple[str, dict | None]:
    """Execute a tool step — loads the saved tool and runs it. Returns (output, cost)."""
    tool = get_by_id("tools", step.get("tool_id", ""))
    if not tool:
        raise RuntimeError(f"Tool '{step.get('tool_id')}' not found")

    tool_type = tool.get("type", 0)
    ctx_str = _format_context(context)
    step_cost = None

    # Resolve the tool's request_inputs from execution context
    resolved_inputs = _resolve_tool_inputs(tool, step, context)
    # Build props list: resolved request_inputs + context values
    tool_props = [{"name": inp["name"], "value": inp.get("value", "")} for inp in resolved_inputs if inp.get("name")]
    ctx_props = [{"name": k, "value": str(v)} for k, v in context.items()]
    all_props = tool_props + ctx_props

    if tool_type == 3:  # Agent
        # Build the agent prompt with resolved inputs clearly stated
        raw_prompt = tool.get("prompt", "") or ""
        if raw_prompt:
            prompt = parse_text(raw_prompt, all_props)
        else:
            prompt = step['instructions']

        # Append resolved tool inputs so the agent knows exact values
        input_lines = []
        for inp in resolved_inputs:
            name = inp.get("name", "")
            val = inp.get("value", "")
            if name and val and not (inp.get("is_default") and val == step.get("instructions")):
                input_lines.append(f"- {name}: {val}")
        if input_lines:
            prompt += "\n\n## Tool Input Values\n" + "\n".join(input_lines)

        # Add previous step context
        if context:
            prompt += f"\n\n## Context from previous steps\n{ctx_str}"

        system_prompt = tool.get("system_prompt", "")
        if system_prompt:
            system_prompt = parse_text(system_prompt, all_props)

        output_parts = []
        agent_error = None
        last_proc_pids: set[int] = set()

        async def _check_processes():
            """Send process status updates when active processes change."""
            nonlocal last_proc_pids
            status = get_proc_status()
            current_pids = {p["pid"] for p in status["processes"] if p.get("running")}
            if current_pids != last_proc_pids:
                last_proc_pids = current_pids
                await ws_send({"type": "processes", "step_id": step["id"], "processes": status["processes"]})

        async for event in run_agent_loop(
            prompt=prompt,
            tool_name=tool.get("name", "tool"),
            tool_id=tool["id"],
            model=model or tool.get("model", ""),
            system_prompt=system_prompt,
            mcp_servers=tool.get("mcp_servers"),
            stop_check=(lambda: run_id in stop_commands) if run_id else None,
        ):
            if run_id and run_id in stop_commands:
                break
            if event.get("type") == "text":
                output_parts.append(event["text"])
                await ws_send({"type": "step_delta", "step_id": step["id"], "text": event["text"]})
            elif event.get("type") == "error":
                agent_error = event.get("text", "Unknown agent error")
                await ws_send({"type": "step_delta", "step_id": step["id"], "text": f"\n[ERROR: {agent_error}]"})
            elif event.get("type") == "tool_call":
                await ws_send({"type": "step_tool_call", "step_id": step["id"],
                              "name": event["name"], "input": event.get("input", {})})
            elif event.get("type") == "tool_result":
                await ws_send({"type": "step_tool_result", "step_id": step["id"],
                              "name": event["name"], "result": str(event.get("result", ""))[:500]})
                await _check_processes()  # Check after each tool execution
            elif event.get("type") == "usage":
                step_cost = _make_cost(
                    event.get("model", model),
                    event.get("input_tokens", 0),
                    event.get("output_tokens", 0),
                    step.get("name", step["id"]),
                )
            await _check_processes()  # Check on every event

        # Final check — processes may have finished
        await _check_processes()

        if agent_error and not output_parts:
            raise RuntimeError(f"Agent failed: {agent_error}")
        return "".join(output_parts), step_cost

    elif tool_type == 1:  # Endpoint
        # Resolve URL, body, query, headers using the tool's request_inputs + context
        url = parse_text(tool.get("endpoint_url", ""), all_props)
        method_map = {0: "GET", 1: "POST", 2: "PUT", 3: "DELETE"}
        method = method_map.get(tool.get("endpoint_method", 0), "GET")

        headers = _kv_resolve(tool.get("endpoint_headers") or [], all_props)
        query = _kv_resolve(tool.get("endpoint_query") or [], all_props)

        body = None
        if method in ("POST", "PUT"):
            body = _kv_resolve(tool.get("endpoint_body") or [], all_props)

        await ws_send({"type": "step_delta", "step_id": step["id"], "text": f"Calling {method} {url}...\n"})

        try:
            ep_timeout = tool.get("endpoint_timeout", 60) or 60
            async with httpx.AsyncClient(timeout=ep_timeout) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=query)
                elif method == "POST":
                    resp = await client.post(url, headers=headers, params=query, json=body)
                elif method == "PUT":
                    resp = await client.put(url, headers=headers, params=query, json=body)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers, params=query)
                else:
                    resp = await client.get(url, headers=headers, params=query)

                # Parse response using tool's response_structure if defined
                response_structure = tool.get("response_structure") or []
                output, parsed_fields = _parse_endpoint_response(resp.text, response_structure)

                # Store parsed fields in step so execute_plan can inject them into context
                if parsed_fields:
                    step["_parsed_fields"] = parsed_fields

                await ws_send({"type": "step_delta", "step_id": step["id"], "text": output})
                return output, None
        except Exception as e:
            raise RuntimeError(f"HTTP request failed: {e}") from e

    else:  # LLM tool (type 0)
        # Resolve prompt and system_prompt using request_inputs + context
        tool_prompt = tool.get("prompt", "") or ""
        system_prompt = tool.get("system_prompt", "") or ""

        if tool_prompt:
            tool_prompt = parse_text(tool_prompt, all_props)
        if system_prompt:
            system_prompt = parse_text(system_prompt, all_props)

        # Append step instructions + context if prompt has no remaining templates
        prompt = f"{tool_prompt}\n\n## Additional Context\n{step['instructions']}\n\n## Previous Step Outputs\n{ctx_str}"

        output_parts = []
        async for chunk in chat_stream(
            [{"role": "user", "content": prompt}],
            model or tool.get("model", ""),
            system_prompt,
        ):
            if chunk.get("type") == "text":
                output_parts.append(chunk["text"])
                await ws_send({"type": "step_delta", "step_id": step["id"], "text": chunk["text"]})
            elif chunk.get("type") == "usage":
                step_cost = _make_cost(
                    chunk.get("model", model),
                    chunk.get("input_tokens", 0),
                    chunk.get("output_tokens", 0),
                    step.get("name", step["id"]),
                )
        return "".join(output_parts), step_cost


async def execute_plan(run: dict, model: str, ws_send, wait_for_answer, planning_cost: dict | None = None) -> dict:
    """Execute a plan step by step, streaming progress via ws_send.

    ws_send: async callable that sends a dict message to the frontend
    wait_for_answer: async callable that waits for user answers (for ask_user steps)
    planning_cost: optional cost dict from the planning phase
    Returns the updated run dict.
    """
    run_id = run.get("id", "")
    plan = run.get("plan", [])
    if not plan:
        return run

    context = {}
    # Pre-populate context with input values
    input_values = run.get("input_values") or {}
    for k, v in input_values.items():
        context[k] = v

    run["status"] = STATUS_RUNNING
    upsert("task_runs", run)

    all_costs = []
    if planning_cost:
        all_costs.append(planning_cost)

    try:
        for step in plan:
            step_id = step["id"]
            step_type = step.get("type", "reasoning")

            # Check stop before starting each step
            if run_id and run_id in stop_commands:
                step["status"] = "failed"
                step["output"] = "Stopped by user"
                await ws_send({"type": "step_error", "step_id": step_id, "error": "Stopped by user"})
                run["status"] = STATUS_FAILED
                run["total_cost"] = _sum_costs(all_costs)
                upsert("task_runs", run)
                return run

            # Check if step should be skipped (user removed it)
            if step.get("status") == "skipped":
                await ws_send({"type": "step_complete", "step_id": step_id, "output": "(Skipped)"})
                continue

            # Per-step model override (user can change in approval mode)
            step_model = step.get("model") or model

            step["status"] = "running"
            await ws_send({"type": "step_start", "step_id": step_id, "name": step.get("name", ""), "model": step_model})
            upsert("task_runs", run)

            step_start_time = time.time()

            # Resolve template variables in step instructions and tool_inputs from context
            ctx_props = [{"name": k, "value": str(v)} for k, v in context.items()]
            if step.get("instructions"):
                step["instructions"] = parse_text(step["instructions"], ctx_props)
            if step.get("tool_inputs"):
                for k, v in step["tool_inputs"].items():
                    if v and "{{" in v:
                        step["tool_inputs"][k] = parse_text(v, ctx_props)

            try:
                step_cost = None

                if step_type == "ask_user":
                    questions = step.get("questions", [])
                    if not questions:
                        # Generate questions dynamically
                        questions = [{"id": "q1", "text": step.get("instructions", "Please provide more details."), "type": "text"}]

                    await ws_send({"type": "ask_user", "step_id": step_id, "questions": questions})
                    answers = await wait_for_answer(step_id)

                    # Format answers as output
                    q_map = {q["id"]: q["text"] for q in questions}
                    lines = []
                    for a in answers:
                        q_text = q_map.get(a.get("id"), "")
                        lines.append(f"Q: {q_text}\nA: {a.get('answer', '')}")
                    output = "\n\n".join(lines)

                elif step_type == "tool":
                    output, step_cost = await _execute_tool_step(step, context, step_model, ws_send, run_id=run_id)

                else:  # reasoning
                    output, step_cost = await _execute_reasoning_step(step, context, step_model, ws_send)

                step_duration = round(time.time() - step_start_time, 1)

                step["output"] = output
                step["status"] = "completed"
                step["duration_s"] = step_duration
                context[step.get("name", step_id)] = output

                # If tool step parsed response fields, inject them individually into context
                parsed_fields = step.pop("_parsed_fields", None)
                if parsed_fields:
                    for field_name, field_value in parsed_fields.items():
                        context[field_name] = str(field_value)

                if step_cost:
                    step["cost"] = step_cost
                    all_costs.append(step_cost)

                # Send step_complete with cost and timing info
                complete_msg = {
                    "type": "step_complete", "step_id": step_id,
                    "output": output[:2000], "duration_s": step_duration,
                    "model": step_model,
                }
                if step_cost:
                    complete_msg["cost"] = step_cost
                await ws_send(complete_msg)

            except Exception as e:
                logger.error("Step %s failed: %s", step_id, e, exc_info=True)
                step["status"] = "failed"
                step["output"] = f"Error: {e}"
                await ws_send({"type": "step_error", "step_id": step_id, "error": str(e)})
                run["status"] = STATUS_FAILED
                run["total_cost"] = _sum_costs(all_costs)
                upsert("task_runs", run)
                return run

            upsert("task_runs", run)

        # All steps completed
        run["status"] = STATUS_COMPLETED
        # Use last step's output as the run output
        last_step = plan[-1] if plan else {}
        run["output"] = last_step.get("output", "")
        run["total_cost"] = _sum_costs(all_costs)
        upsert("task_runs", run)

    except asyncio.CancelledError:
        run["status"] = STATUS_FAILED
        run["total_cost"] = _sum_costs(all_costs)
        upsert("task_runs", run)
        raise
    finally:
        # Clean up stop flag
        if run_id:
            stop_commands.discard(run_id)

    return run
