"""
Pipeline engine - graph-based pipeline execution.
Ported from V3's pipelineApi.py with simplifications.
"""

import asyncio
import json
import os
import re
import traceback
from typing import Optional

from database import get_by_id, get_uid, get_all, upsert, now_iso
from event_bus import broadcast
from services.template_engine import parse_text, parse_json, add_prop
from services.llm import chat_stream, chat_complete, chat_with_tools, evaluate_condition
from services.js_runner import run_js
from services.agent_service import run_agent_loop
from services.pipeline_logger import run_log, flush_to_run
from models.enums import ToolType, PipelineStatusType, EndpointMethod
import httpx

MAX_CONCURRENCY = 5


def _build_json_schema(fields: list[dict]) -> dict:
    """Convert ResponseField[] tree to JSON Schema for forced tool_use."""
    props = {}
    required = []
    for f in fields:
        key = f.get("key", "")
        if not key:
            continue
        ft = f.get("type", "string")
        children = f.get("children", [])
        if ft == "object" and children:
            props[key] = _build_json_schema(children)
        elif ft == "number":
            props[key] = {"type": "number"}
        elif ft == "boolean":
            props[key] = {"type": "boolean"}
        else:
            props[key] = {"type": "string"}
        required.append(key)
    return {"type": "object", "properties": props, "required": required}


def _kv_to_dict(raw, props_chain: list = None, idx: int = 0) -> dict:
    """Convert a KV array or legacy JSON string to a resolved dict.

    Args:
        raw: list of {key, value} dicts, a JSON string (legacy), or empty
        props_chain: list of property lists to resolve templates through
        idx: iteration index for parse_text
    """
    if props_chain is None:
        props_chain = []

    # New format: list of {key, value} dicts
    if isinstance(raw, list):
        result = {}
        for pair in raw:
            if isinstance(pair, dict) and pair.get("key"):
                val = pair.get("value", "")
                for props in props_chain:
                    val = parse_text(val, props, idx)
                result[pair["key"]] = val
        return result

    # Legacy format: JSON string
    if isinstance(raw, str) and raw.strip():
        # First resolve templates in the raw string
        resolved = raw
        for props in props_chain:
            resolved = parse_json(resolved, props, idx) or resolved
        try:
            parsed = json.loads(resolved)
            if isinstance(parsed, dict):
                return parsed
            # Could be a KV array stored as string
            if isinstance(parsed, list):
                result = {}
                for pair in parsed:
                    if isinstance(pair, dict) and pair.get("key"):
                        val = pair.get("value", "")
                        for props in props_chain:
                            val = parse_text(val, props, idx)
                        result[pair["key"]] = val
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    return {}
async def _validate_step_output(step: dict, output: str, pl_run: dict) -> tuple[bool, str, dict]:
    """Validate that a step's output matches its input requirements using a low-cost model.
    Returns (passed, reason, usage_dict)."""
    # Determine which model to use: step override > pipeline default > haiku fallback
    pipeline_default = pl_run.get("validation_model", "") or pl_run.get("pipeline_snapshot", {}).get("validation_model", "")
    model = step.get("validation_model", "") or pipeline_default or "claude-haiku-4-5-20251001"

    step_name = step.get("name", "Unknown")
    step_inputs = step.get("resolved_inputs") or step.get("inputs", [])
    input_text = ""
    for inp in step_inputs:
        name = inp.get("name", "")
        value = inp.get("value", "")
        if value:
            input_text += f"- {name}: {value}\n"

    if not input_text.strip():
        input_text = "(No explicit inputs provided)"

    system_prompt = (
        "You are an output validator for a pipeline step. Your job is to determine whether "
        "the step's output adequately addresses what was requested by its inputs. "
        "Respond with a JSON object: {\"passed\": true/false, \"reason\": \"brief explanation\"}. "
        "Be pragmatic - only fail outputs that clearly do not match the requested task or are obviously wrong, "
        "empty, or nonsensical. Minor formatting differences are acceptable."
    )

    user_msg = (
        f"Step: {step_name}\n\n"
        f"Inputs:\n{input_text}\n\n"
        f"Output:\n{output[:4000]}\n\n"
        "Does this output adequately address the inputs? Respond with JSON only."
    )

    try:
        response_text, usage = await chat_complete(
            [{"role": "user", "content": user_msg}],
            model,
            system_prompt,
        )
        # Parse response

        m = re.search(r'\{[\s\S]*?"passed"\s*:\s*(true|false)[\s\S]*?\}', response_text, re.IGNORECASE)
        if m:
            parsed = json.loads(m.group(0))
            return bool(parsed.get("passed", True)), parsed.get("reason", ""), usage
        # If we can't parse, assume passed (don't block on parsing errors)
        return True, "Validation response could not be parsed", usage
    except Exception as e:
        # Don't fail the step if validation itself errors
        return True, f"Validation error: {e}", {}


stop_commands: set[str] = set()

# Maps (run_id, step_id) -> {"event": asyncio.Event, "answers": list}
_pending_responses: dict[tuple[str, str], dict] = {}


def submit_user_response(run_id: str, step_id: str, answers: list[dict]):
    key = (run_id, step_id)
    if key in _pending_responses:
        _pending_responses[key]["answers"] = answers
        _pending_responses[key]["event"].set()


def _parse_ask_user_response(text: str) -> dict:
    """Extract JSON from LLM response. Handles ```json fences and plain JSON."""
    if not text or not isinstance(text, str):
        return {"status": "ready", "summary": str(text or "")}

    import re

    # Try markdown fenced JSON first — capture everything between fences
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        block = m.group(1).strip()
        if block.startswith("{"):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass

    # Try raw JSON: find outermost { ... } by bracket counting
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    # Last resort: first { to last } (handles simple cases the bracket counter missed)
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire text as a "ready" summary
    return {"status": "ready", "summary": text}


def _normalize_questions(questions) -> list[dict]:
    """Validate and normalize a questions list from the LLM. Returns [] if invalid."""
    if not isinstance(questions, list):
        return []
    result = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        nq = {
            "id": str(q.get("id", f"q{i + 1}")),
            "text": str(q.get("text", q.get("label", q.get("question", "")))),
            "type": str(q.get("type", "text")),
        }
        if not nq["text"]:
            continue  # skip questions with no text
        if nq["type"] not in ("text", "choice"):
            nq["type"] = "text"
        opts = q.get("options")
        if nq["type"] == "choice" and isinstance(opts, list) and len(opts) > 0:
            nq["options"] = [str(o) for o in opts]
        elif nq["type"] == "choice":
            nq["type"] = "text"  # no valid options → fall back to text
        result.append(nq)
    return result


def stop_pipeline(run_id: str):
    stop_commands.add(run_id)


# ── Memory helpers ─────────────────────────────────────────────────

def _get_step_memories(pipeline_run: dict, step_id: str) -> list[dict]:
    """Find all memory nodes connected to a step via _memory edges."""
    edges = pipeline_run.get("pipeline_snapshot", {}).get("edges", [])
    memories_by_id = {m["id"]: m for m in pipeline_run.get("memories", [])}
    connected = []
    for edge in edges:
        if edge.get("source") == step_id and (edge.get("source_handle") or "").endswith("_memory"):
            mem = memories_by_id.get(edge.get("target"))
            if mem and mem not in connected:
                connected.append(mem)
    return connected


def _build_memory_messages(memories: list[dict]) -> list[dict]:
    """Build a sorted messages array from all connected memories."""
    all_msgs = []
    for mem in memories:
        for msg in mem.get("messages", []):
            all_msgs.append(msg)
    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return [{"role": m["role"], "content": m["content"]} for m in all_msgs]


def _append_to_memory(pipeline_run: dict, memory: dict, user_content: str,
                       assistant_content: str, step_name: str):
    """Append a user+assistant exchange to a memory."""
    ts = now_iso()
    msgs = memory.setdefault("messages", [])
    msgs.append({"role": "user", "content": user_content, "step_name": step_name, "timestamp": ts})
    msgs.append({"role": "assistant", "content": assistant_content, "step_name": step_name, "timestamp": ts})
    max_msgs = memory.get("max_messages", 0)
    if max_msgs > 0 and len(msgs) > max_msgs * 2:
        memory["messages"] = msgs[-(max_msgs * 2):]


def _save_long_term_memory(pipeline_id: str, memory: dict):
    """Persist a long-term memory to the database."""
    existing = get_all("pipeline_memories",
        "pipeline_id = ? AND memory_node_id = ?", (pipeline_id, memory["id"]))
    upsert("pipeline_memories", {
        "id": existing[0]["id"] if existing else get_uid(),
        "pipeline_id": pipeline_id,
        "memory_node_id": memory["id"],
        "name": memory.get("name", ""),
        "messages": memory.get("messages", []),
    })


def build_rerun(old_run: dict, pipeline: dict, from_step_id: str) -> dict:
    """Create a new pipeline run that reuses completed outputs before from_step_id."""
    import copy

    old_steps = old_run.get("steps", [])
    old_steps_by_id = {s["id"]: s for s in old_steps}

    # Build fresh step records from the CURRENT pipeline definition
    new_steps = []
    for ps in pipeline.get("steps", []):
        new_steps.append({
            "id": ps.get("id"),
            "name": ps.get("name", ""),
            "tool_id": ps.get("tool_id", ""),
            "tool": ps.get("tool"),
            "inputs": copy.deepcopy(ps.get("inputs", [])),
            "outputs": [],
            "status": PipelineStatusType.Pending,
            "status_text": "",
            "call_cost": [],
            "tool_outputs": [],
            "iteration_outputs": [],
            "split_count": 0,
            "next_steps": ps.get("next_steps", []),
            "next_steps_true": ps.get("next_steps_true", []),
            "next_steps_false": ps.get("next_steps_false", []),
            "is_start": ps.get("is_start", False),
            "disabled": ps.get("disabled", False),
            "pre_process": ps.get("pre_process", ""),
            "post_process": ps.get("post_process", ""),
        })

    new_steps_by_id = {s["id"]: s for s in new_steps}

    # BFS from start steps to find all steps BEFORE from_step_id
    start_ids = [s["id"] for s in new_steps if s.get("is_start")]
    if not start_ids and new_steps:
        start_ids = [new_steps[0]["id"]]

    before_ids: set[str] = set()
    queue = list(start_ids)
    visited: set[str] = set()

    while queue:
        sid = queue.pop(0)
        if sid in visited:
            continue
        visited.add(sid)

        if sid == from_step_id:
            # Don't add this step to before_ids; stop traversal on this branch
            continue

        before_ids.add(sid)
        s = new_steps_by_id.get(sid)
        if s:
            for nid in s.get("next_steps", []) + s.get("next_steps_true", []) + s.get("next_steps_false", []):
                if nid not in visited:
                    queue.append(nid)

    # Copy outputs from old run for "before" steps
    for ns in new_steps:
        if ns["id"] in before_ids and ns["id"] in old_steps_by_id:
            old_s = old_steps_by_id[ns["id"]]
            ns["outputs"] = copy.deepcopy(old_s.get("outputs", []))
            ns["call_cost"] = copy.deepcopy(old_s.get("call_cost", []))
            ns["tool_outputs"] = copy.deepcopy(old_s.get("tool_outputs", []))
            ns["iteration_outputs"] = copy.deepcopy(old_s.get("iteration_outputs", []))
            ns["split_count"] = old_s.get("split_count", 0)
            ns["status"] = PipelineStatusType.Completed

    new_run = {
        "id": get_uid(),
        "pipeline_id": old_run.get("pipeline_id", ""),
        "pipeline_snapshot": copy.deepcopy(pipeline),
        "steps": new_steps,
        "inputs": copy.deepcopy(old_run.get("inputs", [])),
        "outputs": [],
        "status": PipelineStatusType.Running,
        "current_step": 0,
        "guidance": pipeline.get("guidance", old_run.get("guidance", "")),
        "created_at": now_iso(),
        "rerun_from": {"run_id": old_run.get("id", ""), "step_id": from_step_id},
    }

    return new_run


def _snapshot_step_history(step: dict):
    """Snapshot step execution state into history before re-execution."""
    if step.get("outputs"):
        step.setdefault("execution_history", []).append({
            "outputs": step.get("outputs", []),
            "call_cost": step.get("call_cost", []),
            "iteration_outputs": step.get("iteration_outputs"),
            "split_count": step.get("split_count", 0),
            "status_text": step.get("status_text", ""),
            "prompt_used": step.get("prompt_used"),
        })
        step["outputs"] = []
        step["call_cost"] = []
        step["iteration_outputs"] = None
        step["split_count"] = 0
        step["status_text"] = ""
        step["prompt_used"] = None
        step["tool_outputs"] = []


def _resolve_template(text: str, iter_props: list, output_props: list, other_inputs: list, idx: int = 0) -> str:
    """Resolve a template string through the standard props chain."""
    text = parse_text(text, iter_props, idx)
    text = parse_text(text, output_props, idx)
    text = parse_text(text, other_inputs, idx)
    return text


def _resolve_prompt_and_system(tool: dict, inp: str, iter_props: list, output_props: list,
                                other_inputs: list, idx: int = 0) -> tuple[str, str]:
    """Resolve both prompt and system_prompt from a tool definition."""
    raw_prompt = tool.get("prompt", "") or ""
    if raw_prompt:
        user_content = _resolve_template(raw_prompt, iter_props, output_props, other_inputs, idx)
    else:
        user_content = str(inp)

    system_prompt = tool.get("system_prompt", "")
    if system_prompt:
        system_prompt = _resolve_template(system_prompt, iter_props, output_props, other_inputs, idx)

    return user_content, system_prompt


def _prep_step(pipeline_run: dict, step: dict, tool: dict) -> tuple[list, Optional[dict], list, list]:
    """Resolve template variables for a step's tool inputs.

    Resolution chain: step inputs -> previous outputs -> action params -> pipeline inputs -> pipeline outputs
    """
    output_props = []
    step_action_params = []

    for prev_step in pipeline_run.get("steps", []):
        # Collect tool outputs as action params
        tool_outputs = prev_step.get("tool_outputs", [])
        if tool_outputs:
            combined = "\n".join(tool_outputs)
            step_action_params.append({"name": f"{prev_step.get('name', '')}Actions", "value": combined})

        for output in prev_step.get("outputs", []):
            output_props.append(output)

    # First resolve the step's own inputs against outputs/pipeline inputs
    step_inputs = step.get("inputs", [])
    for si in step_inputs:
        si["value"] = parse_text(si.get("value", ""), output_props)
        si["value"] = parse_text(si["value"], step_action_params)
        si["value"] = parse_text(si["value"], pipeline_run.get("inputs", []))
        si["value"] = parse_text(si["value"], pipeline_run.get("outputs", []))

    # Store resolved inputs for display in the UI
    step["resolved_inputs"] = [
        {"name": si.get("name", ""), "value": si.get("value", "")}
        for si in step_inputs if si.get("value")
    ]

    # If step's default Input is still empty, populate it from previous step output or pipeline input
    main_step_input = next(
        (x for x in step_inputs if x.get("is_default") or x.get("name") in ("input", "Input")),
        None,
    )
    if main_step_input and not main_step_input.get("value"):
        # Try last completed step's output first
        for prev_step in reversed(pipeline_run.get("steps", [])):
            if prev_step.get("id") == step.get("id"):
                continue
            prev_outputs = prev_step.get("outputs", [])
            if prev_outputs and prev_outputs[0].get("value"):
                main_step_input["value"] = prev_outputs[0]["value"]
                break
        # Fallback to first pipeline input with a value
        if not main_step_input.get("value"):
            for pi in pipeline_run.get("inputs", []):
                if pi.get("value"):
                    main_step_input["value"] = pi["value"]
                    break

    # Now resolve tool request_inputs against the (now-populated) step inputs
    request_inputs = tool.get("request_inputs", [])
    for inp in request_inputs:
        inp["value"] = parse_text(inp.get("value", ""), step_inputs)
        inp["value"] = parse_text(inp["value"], output_props)
        inp["value"] = parse_text(inp["value"], step_action_params)
        inp["value"] = parse_text(inp["value"], pipeline_run.get("inputs", []))
        inp["value"] = parse_text(inp["value"], pipeline_run.get("outputs", []))

    main_input = next(
        (x for x in request_inputs if x.get("is_default") or x.get("name") in ("input", "Input")),
        None,
    )
    other_inputs = [x for x in request_inputs if not x.get("is_default") and x.get("name") not in ("input", "Input")]
    other_inputs.extend(pipeline_run.get("inputs", []))
    other_inputs.extend(pipeline_run.get("outputs", []))

    return step_action_params, main_input, other_inputs, output_props


async def _execute_step(pipeline_run: dict, step: dict, tool: dict, sem: asyncio.Semaphore) -> tuple[str, Optional[str], list]:
    """Execute a single pipeline step and return (chaining_output, agent_text_or_none, iteration_outputs)."""
    async with sem:
        run_id = pipeline_run.get("id", "")
        from services.artifact_service import init_artifact_context
        init_artifact_context(run_id)
        step_id = step.get("id", "")
        tool_type = tool.get("type", ToolType.LLM)

        step_action_params, main_input, other_inputs, output_props = _prep_step(pipeline_run, step, tool)
        prompt = main_input.get("value", "") if main_input else ""

        # Pre-process JS
        pre_process = step.get("pre_process", "")
        inputs_list = [prompt]
        if pre_process and pre_process.strip():
            try:
                result = run_js(pre_process, prompt)
                if isinstance(result, list):
                    inputs_list = result
                else:
                    inputs_list = [str(result)]
            except Exception as e:
                broadcast("step_error", {"run_id": run_id, "step_id": step_id, "error": f"Pre-process error: {e}"})


        full_output = ""
        agent_text_out = None
        iteration_outputs = []
        cost_before = len(step.get("call_cost", []))

        # Broadcast split info so frontend shows iteration count immediately
        if len(inputs_list) > 1:
            broadcast("step_split", {"run_id": run_id, "step_id": step_id, "total": len(inputs_list)})

        for idx, inp in enumerate(inputs_list):
            if run_id in stop_commands:
                return full_output, agent_text_out, iteration_outputs

            # Broadcast iteration start
            if len(inputs_list) > 1:
                broadcast("iteration_start", {
                    "run_id": run_id, "step_id": step_id,
                    "index": idx, "total": len(inputs_list),
                    "input": str(inp)[:200],
                })

            output_before = full_output
            iter_agent_text = None

            # Build per-iteration input props for template resolution
            inp_name = main_input.get("name", "Input") if main_input else "Input"
            iter_props = [{"name": inp_name, "value": str(inp)}]
            # Add indexed props so {{Input[0]}} etc. work
            for i, item in enumerate(inputs_list):
                iter_props.append({"name": f"{inp_name}[{i}]", "value": str(item)})

            if tool_type == ToolType.LLM:
                model = tool.get("model", "")
                user_content, system_prompt = _resolve_prompt_and_system(
                    tool, inp, iter_props, output_props, other_inputs, idx)

                # RAG support
                chatbot_id = tool.get("chatbot_id", "")
                if chatbot_id:
                    try:
                        from services.rag_service import query_index as rag_query
                    except ImportError:
                        rag_query = None
                    if rag_query:
                        results = await asyncio.to_thread(rag_query, chatbot_id, user_content)
                    else:
                        results = []
                    context = "\n\n".join([r["text"] for r in results])
                    if context:
                        system_prompt += f"\n\nContext:\n{context}"

                step["prompt_used"] = {"system": system_prompt, "user": user_content}

                # Inject memory messages
                step_memories = _get_step_memories(pipeline_run, step_id)
                memory_messages = _build_memory_messages(step_memories) if step_memories else []
                messages = memory_messages + [{"role": "user", "content": user_content}]

                run_log(run_id, "llm", f"Calling LLM: {model}", step_id=step_id,
                        detail={"prompt_length": len(user_content), "has_rag": bool(chatbot_id),
                                "memory_messages": len(memory_messages)})

                response_structure = tool.get("response_structure", [])
                if response_structure:
                    # Structured output via forced tool_use
                    schema = _build_json_schema(response_structure)
                    struct_tool = {
                        "name": "structured_output",
                        "description": "Return the response in the required structured format.",
                        "input_schema": schema,
                    }
                    result = await chat_with_tools(
                        messages, [struct_tool], model, system_prompt,
                        tool_choice={"type": "tool", "name": "structured_output"},
                    )
                    for block in result.get("content", []):
                        if block.get("type") == "tool_use" and block.get("name") == "structured_output":
                            data = block.get("input", {})
                            full_output += json.dumps(data)
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": json.dumps(data)})
                            break
                    usage = result.get("usage", {})
                    step.setdefault("call_cost", []).append({
                        "detail": step.get("name", ""),
                        "model": usage.get("model", ""),
                        "input_token_count": usage.get("input_tokens", 0),
                        "output_token_count": usage.get("output_tokens", 0),
                    })
                    run_log(run_id, "llm", f"LLM structured output ({usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out)",
                            step_id=step_id, detail={"model": usage.get("model", "")})
                else:
                    async for chunk in chat_stream(messages, model, system_prompt):
                        if run_id in stop_commands:
                            break
                        if chunk.get("type") == "text":
                            full_output += chunk["text"]
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": chunk["text"]})
                        elif chunk.get("type") == "usage":
                            step.setdefault("call_cost", []).append({
                                "detail": step.get("name", ""),
                                "model": chunk.get("model", ""),
                                "input_token_count": chunk.get("input_tokens", 0),
                                "output_token_count": chunk.get("output_tokens", 0),
                            })
                            run_log(run_id, "llm", f"LLM responded ({chunk.get('input_tokens', 0)} in / {chunk.get('output_tokens', 0)} out)",
                                    step_id=step_id, detail={"model": chunk.get("model", ""),
                                    "input_tokens": chunk.get("input_tokens", 0), "output_tokens": chunk.get("output_tokens", 0)})

            elif tool_type == ToolType.Endpoint:
                endpoint = parse_text(tool.get("endpoint_url", ""), iter_props, idx)
                endpoint = parse_text(endpoint, output_props, idx)
                endpoint = parse_text(endpoint, other_inputs, idx)
                method = tool.get("endpoint_method", EndpointMethod.GET)

                props_chain = [iter_props, output_props, other_inputs]
                query_dict = _kv_to_dict(tool.get("endpoint_query", []), props_chain, idx)
                headers = _kv_to_dict(tool.get("endpoint_headers", ""), props_chain, idx)
                body = _kv_to_dict(tool.get("endpoint_body", ""), props_chain, idx)

                run_log(run_id, "endpoint", f"Calling endpoint: {method.name if hasattr(method, 'name') else method} {endpoint}",
                        step_id=step_id)

                ep_timeout = tool.get("endpoint_timeout", 60) or 60
                async with httpx.AsyncClient(timeout=ep_timeout) as http:
                    if method == EndpointMethod.GET:
                        resp = await http.get(endpoint, headers=headers, params=query_dict)
                    elif method == EndpointMethod.POST:
                        resp = await http.post(endpoint, headers=headers, params=query_dict, json=body)
                    elif method == EndpointMethod.PUT:
                        resp = await http.put(endpoint, headers=headers, params=query_dict, json=body)
                    else:
                        resp = await http.delete(endpoint, headers=headers, params=query_dict)
                    full_output += resp.text
                    run_log(run_id, "endpoint", f"Endpoint responded: {resp.status_code} ({len(resp.text)} chars)",
                            step_id=step_id)

            elif tool_type == ToolType.Agent:
                agent_input, agent_system = _resolve_prompt_and_system(
                    tool, inp, iter_props, output_props, other_inputs, idx)

                # Inject memory context into agent input
                agent_step_memories = _get_step_memories(pipeline_run, step_id)
                agent_memory_messages = _build_memory_messages(agent_step_memories) if agent_step_memories else []
                if agent_memory_messages:
                    context = "\n".join(f"[{m['role']}]: {m['content']}" for m in agent_memory_messages)
                    agent_input = f"Previous conversation context:\n{context}\n\n---\nCurrent request:\n{agent_input}"

                step["prompt_used"] = {"system": agent_system, "user": agent_input}

                run_log(run_id, "agent", f"Starting agent loop: {tool.get('name', '')}",
                        step_id=step_id)

                last_tool_result = ""
                had_tool_calls = False
                agent_text = ""
                async for chunk in run_agent_loop(
                    agent_input, tool.get("name", ""), tool.get("id", ""),
                    tool.get("model", ""), agent_system,
                    mcp_servers=tool.get("mcp_servers", []),
                    run_id=run_id, step_id=step_id,
                    stop_check=lambda: run_id in stop_commands,
                ):
                    if run_id in stop_commands:
                        break
                    if chunk.get("type") == "text":
                        agent_text += chunk["text"]
                        broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": chunk["text"]})
                    elif chunk.get("type") == "tool_call":
                        had_tool_calls = True
                        step.setdefault("tool_outputs", []).append(
                            f"Called {chunk['name']} with {json.dumps(chunk.get('input', {}))}"
                        )
                    elif chunk.get("type") == "tool_result":
                        last_tool_result = chunk.get("result", "")
                        step.setdefault("tool_outputs", []).append(
                            f"{chunk['name']} returned: {last_tool_result[:200]}"
                        )
                    elif chunk.get("type") == "artifacts":
                        step.setdefault("artifacts", []).extend(chunk.get("artifacts", []))
                    elif chunk.get("type") == "usage":
                        step.setdefault("call_cost", []).append({
                            "detail": step.get("name", ""),
                            "model": chunk.get("model", ""),
                            "input_token_count": chunk.get("input_tokens", 0),
                            "output_token_count": chunk.get("output_tokens", 0),
                        })
                # For pipeline chaining: use the last tool result as output
                # (not the agent's chatty summary), falling back to agent text
                # if no tools were called
                if had_tool_calls and last_tool_result:
                    agent_raw_output = last_tool_result
                    agent_text_out = agent_text
                    iter_agent_text = agent_text
                else:
                    agent_raw_output = agent_text

                # Structured output post-formatting for agents
                response_structure = tool.get("response_structure", [])
                if response_structure and agent_raw_output:
                    schema = _build_json_schema(response_structure)
                    struct_tool = {
                        "name": "structured_output",
                        "description": "Format the agent's response into the required structure.",
                        "input_schema": schema,
                    }
                    format_msg = [{"role": "user", "content": f"Format the following data into the required structure:\n\n{agent_raw_output}"}]
                    result = await chat_with_tools(
                        format_msg, [struct_tool], tool.get("model", ""), "",
                        tool_choice={"type": "tool", "name": "structured_output"},
                    )
                    for block in result.get("content", []):
                        if block.get("type") == "tool_use" and block.get("name") == "structured_output":
                            full_output += json.dumps(block.get("input", {}))
                            break
                    else:
                        full_output += agent_raw_output
                    usage = result.get("usage", {})
                    step.setdefault("call_cost", []).append({
                        "detail": f"{step.get('name', '')} (format)",
                        "model": usage.get("model", ""),
                        "input_token_count": usage.get("input_tokens", 0),
                        "output_token_count": usage.get("output_tokens", 0),
                    })
                else:
                    full_output += agent_raw_output

            elif tool_type == ToolType.Pipeline:
                # Nested pipeline execution
                nested_pipeline_id = tool.get("pipeline_id", "")
                if nested_pipeline_id:
                    nested_pl = get_by_id("pipelines", nested_pipeline_id)
                    if nested_pl:
                        # Create a sub-run
                        from database import get_uid
                        sub_run = {
                            "id": get_uid(),
                            "pipeline_id": nested_pipeline_id,
                            "pipeline_snapshot": nested_pl,
                            "steps": nested_pl.get("steps", []),
                            "inputs": step.get("inputs", []),
                            "outputs": [],
                            "status": PipelineStatusType.Running,
                            "current_step": 0,
                            "guidance": nested_pl.get("guidance", ""),
                            "created_at": now_iso(),
                            "user_id": pipeline_run.get("user_id", "default"),
                        }
                        upsert("pipeline_runs", sub_run)
                        await run_pipeline(sub_run["id"])
                        # Get results
                        completed = get_by_id("pipeline_runs", sub_run["id"])
                        if completed:
                            for out in completed.get("outputs", []):
                                full_output += str(out.get("value", ""))

            elif tool_type == ToolType.If:
                # AI-powered condition evaluation with forced tool use
                model = tool.get("model", "")
                user_content, system_prompt = _resolve_prompt_and_system(
                    tool, inp, iter_props, output_props, other_inputs, idx)

                step["prompt_used"] = {"system": system_prompt, "user": user_content}

                # Inject memory messages for If step
                if_step_memories = _get_step_memories(pipeline_run, step_id)
                if_memory_messages = _build_memory_messages(if_step_memories) if if_step_memories else []
                if_messages = if_memory_messages + [{"role": "user", "content": user_content}]

                result, reasoning, usage = await evaluate_condition(
                    if_messages, model, system_prompt
                )
                step.setdefault("call_cost", []).append({
                    "detail": step.get("name", ""),
                    "model": usage.get("model", ""),
                    "input_token_count": usage.get("input_tokens", 0),
                    "output_token_count": usage.get("output_tokens", 0),
                })
                step["status_text"] = reasoning
                full_output = "true" if result else "false"
                run_log(run_id, "condition", f"Condition evaluated: {'TRUE' if result else 'FALSE'}",
                        step_id=step_id, detail={"reasoning": reasoning[:200]})

            elif tool_type == ToolType.LoopCounter:
                max_passes = tool.get("max_passes", 5)
                count = step.get("_loop_count", 0) + 1
                step["_loop_count"] = count
                if count > max_passes:
                    step["_loop_halted"] = True
                    step["status_text"] = f"Max passes ({max_passes}) reached — halting branch"
                    full_output = ""
                    run_log(run_id, "pipeline", f"Loop halted — max passes ({max_passes}) reached", step_id=step_id)
                else:
                    step["_loop_halted"] = False
                    step["status_text"] = f"Pass {count} of {max_passes}"
                    full_output = str(inp)
                    run_log(run_id, "pipeline", f"Loop pass {count} of {max_passes}", step_id=step_id)

            elif tool_type == ToolType.AskUser:
                model = tool.get("model", "")
                user_content, system_prompt = _resolve_prompt_and_system(
                    tool, inp, iter_props, output_props, other_inputs, idx)

                # Inject memory messages for AskUser step
                ask_step_memories = _get_step_memories(pipeline_run, step_id)
                ask_memory_messages = _build_memory_messages(ask_step_memories) if ask_step_memories else []

                # Conversation loop
                messages = ask_memory_messages + [{"role": "user", "content": user_content}]
                max_rounds = 10
                ask_key = (run_id, step_id)

                try:
                    for round_num in range(max_rounds):
                        # LLM call with error handling
                        try:
                            response_text, usage = await chat_complete(messages, model, system_prompt)
                        except Exception as llm_err:
                            run_log(run_id, "pipeline", f"AskUser LLM call failed (round {round_num + 1}): {llm_err}",
                                    step_id=step_id, level="error")
                            full_output = f"LLM call failed: {llm_err}"
                            break

                        if not response_text:
                            run_log(run_id, "pipeline", f"AskUser LLM returned empty response (round {round_num + 1})",
                                    step_id=step_id, level="warn")
                            full_output = ""
                            break

                        step.setdefault("call_cost", []).append({
                            "detail": step.get("name", ""),
                            "model": usage.get("model", ""),
                            "input_token_count": usage.get("input_tokens", 0),
                            "output_token_count": usage.get("output_tokens", 0),
                        })
                        messages.append({"role": "assistant", "content": response_text})

                        parsed = _parse_ask_user_response(response_text)
                        run_log(run_id, "pipeline",
                                f"AskUser round {round_num + 1}: status={parsed.get('status', '?')}",
                                step_id=step_id, level="debug")

                        if parsed.get("status") == "ready":
                            full_output = parsed.get("summary", response_text)
                            break
                        elif parsed.get("status") == "questions":
                            raw_questions = parsed.get("questions", [])
                            questions = _normalize_questions(raw_questions)

                            if not questions:
                                # LLM said "questions" but gave nothing usable — re-prompt once
                                run_log(run_id, "pipeline",
                                        f"AskUser round {round_num + 1}: questions status but no valid questions, "
                                        f"re-prompting LLM",
                                        step_id=step_id, level="warn")
                                messages.append({"role": "user", "content":
                                    "Your response indicated questions but none were valid. "
                                    "Please respond with valid JSON containing a \"questions\" array "
                                    "where each question has \"id\", \"text\", and \"type\" (text or choice). "
                                    "If you have no questions, respond with {\"status\": \"ready\", \"summary\": \"...\"}."
                                })
                                continue

                            _pending_responses[ask_key] = {"event": asyncio.Event(), "answers": None}

                            broadcast("ask_user", {
                                "run_id": run_id,
                                "step_id": step_id,
                                "questions": questions,
                                "round": round_num + 1,
                            })

                            # Update pipeline status to WaitingForInput
                            pipeline_run["status"] = PipelineStatusType.WaitingForInput
                            upsert("pipeline_runs", pipeline_run)

                            # Wait for user response (with timeout)
                            try:
                                await asyncio.wait_for(
                                    _pending_responses[ask_key]["event"].wait(), timeout=3600
                                )
                            except asyncio.TimeoutError:
                                full_output = "Timed out waiting for user response."
                                run_log(run_id, "pipeline", "AskUser timed out waiting for response",
                                        step_id=step_id, level="warn")
                                break
                            finally:
                                # Always restore running status after wait completes or times out
                                pipeline_run["status"] = PipelineStatusType.Running
                                upsert("pipeline_runs", pipeline_run)

                            answers = _pending_responses.pop(ask_key, {}).get("answers") or []

                            # Feed answers back to LLM
                            answer_parts = []
                            for a in answers:
                                if isinstance(a, dict):
                                    answer_parts.append(f"- {a.get('id', '?')}: {a.get('answer', '')}")
                            answer_text = "\n".join(answer_parts) if answer_parts else "(no answers provided)"
                            messages.append({"role": "user", "content": f"User answers:\n{answer_text}"})

                            # Broadcast that answers were received
                            broadcast("ask_user_answered", {"run_id": run_id, "step_id": step_id})
                        else:
                            # Unrecognized status, treat as ready
                            full_output = parsed.get("summary", response_text)
                            break
                    else:
                        # Max rounds reached, use last LLM response as fallback
                        run_log(run_id, "pipeline",
                                f"AskUser reached max {max_rounds} rounds, using last response",
                                step_id=step_id, level="warn")
                        full_output = messages[-1]["content"] if messages else ""
                finally:
                    # Ensure cleanup: remove stale pending responses and fix pipeline status
                    _pending_responses.pop(ask_key, None)
                    if pipeline_run.get("status") == PipelineStatusType.WaitingForInput:
                        pipeline_run["status"] = PipelineStatusType.Running
                        upsert("pipeline_runs", pipeline_run)

                step["prompt_used"] = {"system": system_prompt, "user": user_content}

            elif tool_type == ToolType.FileUpload:
                # Resolve prompt template for the user message
                message = parse_text(tool.get("prompt", "Upload file(s)"), iter_props, idx)
                message = parse_text(message, output_props, idx)

                # Broadcast upload request
                ask_key = (run_id, step_id)
                _pending_responses[ask_key] = {"event": asyncio.Event(), "answers": None}
                broadcast("file_upload_request", {
                    "run_id": run_id, "step_id": step_id,
                    "message": message,
                })

                # Set WaitingForInput, wait for response
                pipeline_run["status"] = PipelineStatusType.WaitingForInput
                upsert("pipeline_runs", pipeline_run)
                try:
                    await asyncio.wait_for(_pending_responses[ask_key]["event"].wait(), timeout=3600)
                except asyncio.TimeoutError:
                    full_output = "Timed out waiting for file upload."
                    run_log(run_id, "pipeline", "FileUpload timed out waiting for response",
                            step_id=step_id, level="warn")
                    break
                finally:
                    pipeline_run["status"] = PipelineStatusType.Running
                    upsert("pipeline_runs", pipeline_run)

                # Get file paths from response
                from config import UPLOADS_DIR as _UP_DIR
                answers = _pending_responses.pop(ask_key, {}).get("answers") or []
                file_names = []
                for a in answers:
                    val = a.get("answer", "") if isinstance(a, dict) else str(a)
                    if val:
                        file_names.extend(v.strip() for v in val.split(",") if v.strip())
                # Output full absolute paths so downstream steps can locate files
                full_paths = [os.path.join(_UP_DIR, run_id, fn) for fn in file_names]
                full_output = json.dumps(full_paths) if full_paths else "[]"
                broadcast("file_upload_complete", {"run_id": run_id, "step_id": step_id})

            elif tool_type == ToolType.Start:
                # Start step: pass through pipeline inputs as output
                pl_inputs = pipeline_run.get("inputs", [])
                if pl_inputs:
                    # Store each input individually (will be set as step outputs after return)
                    step["_start_outputs"] = [
                        {"name": p.get("name", "Input"), "value": str(p.get("value", ""))}
                        for p in pl_inputs if p.get("value")
                    ]
                    full_output = " ".join(
                        str(p.get("value", "")) for p in pl_inputs if p.get("value")
                    ) or inp
                else:
                    full_output = inp

            elif tool_type == ToolType.Wait:
                # Count incoming branches for status display
                all_steps = pipeline_run.get("steps", [])
                incoming_count = sum(
                    1 for s in all_steps
                    if step_id in s.get("next_steps", [])
                    or step_id in s.get("next_steps_true", [])
                    or step_id in s.get("next_steps_false", [])
                )
                step["status_text"] = f"All {incoming_count} branch{'es' if incoming_count != 1 else ''} arrived"
                full_output = str(inp)

            elif tool_type == ToolType.Task:
                # Task step: AI plans + executes a multi-step task
                from services.task_execution_service import generate_plan, execute_plan as exec_task_plan
                from database import get_all as db_get_all

                task_model = tool.get("model", "") or ""
                task_request = _resolve_template(
                    tool.get("prompt", "") or "", iter_props, output_props, other_inputs, idx
                ) or str(inp)

                run_log(run_id, "pipeline", f"Task step: planning for request ({len(task_request)} chars)", step_id=step_id)

                # Build tool catalog from saved tools
                all_tools = db_get_all("tools")
                tool_catalog = [t for t in all_tools if t.get("is_enabled") and t.get("type") in (0, 1, 3)]

                # Generate plan
                plan_result, plan_cost = await generate_plan(task_request, task_model, tool_catalog)
                if plan_cost:
                    step.setdefault("call_cost", []).append({
                        "detail": "Task Planning",
                        "model": plan_cost.get("model", ""),
                        "input_token_count": plan_cost.get("input_tokens", 0),
                        "output_token_count": plan_cost.get("output_tokens", 0),
                    })

                plan_steps = plan_result.get("steps", [])
                if not plan_steps:
                    full_output += f"Task planning returned no steps for: {task_request}"
                    run_log(run_id, "pipeline", "Task planning returned no steps", step_id=step_id, level="warn")
                else:
                    # Stream plan info
                    plan_summary = f"**Task Plan** ({len(plan_steps)} steps): {plan_result.get('goal', '')}\n"
                    for ps in plan_steps:
                        plan_summary += f"  - {ps.get('name', ps['id'])}: {ps.get('type', '?')}\n"
                    broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": plan_summary + "\n---\n"})

                    # Build a task run dict for execute_plan
                    task_run = {
                        "id": f"task_{run_id}_{step_id}",
                        "task_plan_id": "",
                        "request": task_request,
                        "input_values": {},
                        "plan": plan_steps,
                        "status": 1,
                        "output": "",
                        "model": task_model,
                        "total_cost": None,
                    }

                    # Populate input_values from step inputs context
                    for p in other_inputs:
                        if p.get("name") and p.get("value"):
                            task_run["input_values"][p["name"]] = p["value"]
                    # Also add pipeline outputs as context
                    for p in pipeline_run.get("outputs", []):
                        if p.get("name") and p.get("value"):
                            task_run["input_values"][p["name"]] = p["value"]

                    # ws_send adapter: convert task events to pipeline broadcast events
                    async def _task_ws_send(msg: dict):
                        msg_type = msg.get("type", "")
                        if msg_type == "step_delta":
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": msg.get("text", "")})
                        elif msg_type == "step_start":
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id,
                                                       "text": f"\n**[{msg.get('name', '')}]** "})
                        elif msg_type == "step_complete":
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id, "text": "\n"})
                        elif msg_type == "step_error":
                            broadcast("step_stream", {"run_id": run_id, "step_id": step_id,
                                                       "text": f"\n[ERROR: {msg.get('error', '')}]\n"})

                    # wait_for_answer stub — task steps in pipelines don't support ask_user
                    async def _task_wait_for_answer(sid: str):
                        return []

                    result_run = await exec_task_plan(task_run, task_model, _task_ws_send, _task_wait_for_answer, plan_cost)

                    # Aggregate costs from task execution
                    task_total_cost = result_run.get("total_cost") or {}
                    for sc in task_total_cost.get("steps", []):
                        step.setdefault("call_cost", []).append({
                            "detail": sc.get("detail", ""),
                            "model": sc.get("model", ""),
                            "input_token_count": sc.get("input_tokens", 0),
                            "output_token_count": sc.get("output_tokens", 0),
                        })

                    full_output += result_run.get("output", "")
                    run_log(run_id, "pipeline", f"Task completed with status {result_run.get('status')}", step_id=step_id)

            elif tool_type in (ToolType.Pause, ToolType.End):
                full_output = inp

            # Capture per-iteration output
            iter_output = full_output[len(output_before):]
            iter_cost = step.get("call_cost", [])[cost_before:]
            cost_before = len(step.get("call_cost", []))
            iteration_outputs.append({
                "input": str(inp)[:200],
                "output": iter_output,
                "agent_output": iter_agent_text,
                "cost": list(iter_cost),
            })

            # Append to connected memories
            step_memories_for_append = _get_step_memories(pipeline_run, step_id)
            if step_memories_for_append and iter_output:
                step_name = step.get("name", "")
                for mem in step_memories_for_append:
                    _append_to_memory(pipeline_run, mem, str(inp), iter_output, step_name)
                    if mem.get("type") == "long_term":
                        _save_long_term_memory(pipeline_run.get("pipeline_id", ""), mem)
                    broadcast("memory_update", {
                        "run_id": run_id, "memory_id": mem["id"],
                        "message_count": len(mem.get("messages", [])),
                        "latest": mem.get("messages", [])[-2:],
                    })

            # Broadcast iteration complete
            if len(inputs_list) > 1:
                broadcast("iteration_complete", {
                    "run_id": run_id, "step_id": step_id,
                    "index": idx,
                    "output": iter_output[:500],
                    "agent_output": (iter_agent_text or "")[:500] if iter_agent_text else None,
                    "cost": list(iter_cost),
                })

        # Post-process JS
        post_process = step.get("post_process", "")
        if post_process and post_process.strip() and full_output:
            try:
                result = run_js(post_process, full_output)
                full_output = str(result) if result is not None else full_output
            except Exception as e:
                broadcast("step_error", {"run_id": run_id, "step_id": step_id, "error": f"Post-process error: {e}"})

        return full_output, agent_text_out, iteration_outputs


def _get_next_steps(step: dict, output: str) -> list[str]:
    """Determine next steps based on tool type and output."""
    tool_type = step.get("tool", {}).get("type", ToolType.LLM) if step.get("tool") else ToolType.LLM

    if tool_type == ToolType.If:
        if output.strip().lower() in ("true", "1", "yes"):
            return step.get("next_steps_true", []) + step.get("next_steps", [])
        else:
            return step.get("next_steps_false", []) + step.get("next_steps", [])
    elif tool_type == ToolType.LoopCounter:
        if step.get("_loop_halted"):
            return []
        return step.get("next_steps", [])
    else:
        return step.get("next_steps", [])


async def _run_parallel_branch(
    pl_run: dict, next_ids: list[str], steps_by_id: dict, visited: set,
    queue: list, sem: asyncio.Semaphore, run_id: str,
):
    """Execute multiple next steps concurrently, then collect their downstream next steps."""
    parallel_tasks = []
    executed_ids = set()
    for nid in next_ids:
        ns = steps_by_id.get(nid)
        if not ns or nid in visited:
            continue
        visited.add(nid)
        # Skip already-completed steps (resume after pause)
        if ns.get("status") == PipelineStatusType.Completed:
            continue
        executed_ids.add(nid)
        parallel_tasks.append(_run_single_step(pl_run, ns, sem, run_id))

    if parallel_tasks:
        await asyncio.gather(*parallel_tasks, return_exceptions=True)

    # Check if any newly-executed step failed — stop the pipeline
    for nid in executed_ids:
        ns = steps_by_id.get(nid)
        if ns and ns.get("status") == PipelineStatusType.Failed:
            pl_run["status"] = PipelineStatusType.Failed
            upsert("pipeline_runs", pl_run)
            queue.clear()
            return

    # Check if any newly-executed step requested a pause
    for nid in executed_ids:
        ns = steps_by_id.get(nid)
        if ns and ns.get("pause_after") and ns.get("status") == PipelineStatusType.Completed:
            pl_run["status"] = PipelineStatusType.Paused
            upsert("pipeline_runs", pl_run)
            broadcast("pipeline_paused", {"run_id": run_id, "step_id": nid})
            queue.clear()
            return

    # After parallel steps complete, collect their next steps back into the queue
    for nid in next_ids:
        ns = steps_by_id.get(nid)
        if ns and ns.get("status") == PipelineStatusType.Completed:
            output = ""
            for o in ns.get("outputs", []):
                output += str(o.get("value", ""))
            next_next = _get_next_steps(ns, output)
            queue.extend(next_next)


def _clear_loop_visited(steps_by_id: dict, visited: set, next_ids: list[str], loop_step_id: str):
    """BFS from next_ids through the step graph, removing each reachable step from visited
    and resetting status to Pending so they re-execute. Stops at loop_step_id to avoid
    infinite traversal."""
    queue = list(next_ids)
    seen: set[str] = set()
    while queue:
        sid = queue.pop(0)
        if sid in seen or sid == loop_step_id:
            continue
        seen.add(sid)
        visited.discard(sid)
        s = steps_by_id.get(sid)
        if s:
            s["status"] = PipelineStatusType.Pending
            for nid in s.get("next_steps", []) + s.get("next_steps_true", []) + s.get("next_steps_false", []):
                queue.append(nid)


async def run_pipeline(run_id: str):
    """Execute a pipeline run by traversing its step graph."""
    pl_run = get_by_id("pipeline_runs", run_id)
    if not pl_run:
        return

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    steps = pl_run.get("steps", [])
    steps_by_id = {s["id"]: s for s in steps}

    # Initialize memories
    if not pl_run.get("memories"):
        pl_run["memories"] = []
        for m in pl_run.get("pipeline_snapshot", {}).get("memories", []):
            mem = {**m, "messages": []}
            if m.get("type") == "long_term":
                persisted = get_all("pipeline_memories",
                    "pipeline_id = ? AND memory_node_id = ?",
                    (pl_run.get("pipeline_id", ""), m["id"]))
                if persisted:
                    mem["messages"] = persisted[0].get("messages", [])
            pl_run["memories"].append(mem)

    # Find start steps
    start_steps = [s for s in steps if s.get("is_start")]
    if not start_steps:
        # If no explicit start, use first step
        start_steps = steps[:1] if steps else []

    queue = [s["id"] for s in start_steps]
    visited = set()

    run_log(run_id, "pipeline", f"Pipeline started with {len(steps)} steps",
            detail={"start_steps": [s.get("name", "") for s in start_steps]})

    try:
        while queue:
            if run_id in stop_commands:
                pl_run["status"] = PipelineStatusType.Failed
                break

            current_id = queue.pop(0)
            if current_id in visited:
                continue

            step = steps_by_id.get(current_id)
            if not step:
                continue

            # Wait barrier: defer until all incoming branches complete
            step_tool = step.get("tool") or {}
            if step_tool.get("type") == ToolType.Wait:
                incoming = [
                    s for s in steps
                    if current_id in s.get("next_steps", [])
                    or current_id in s.get("next_steps_true", [])
                    or current_id in s.get("next_steps_false", [])
                ]
                all_done = all(
                    s.get("status") in (PipelineStatusType.Completed, PipelineStatusType.Failed)
                    or s.get("disabled")
                    for s in incoming
                )
                if not all_done:
                    continue  # Don't mark visited; will be re-queued by completing branches

            visited.add(current_id)

            if step.get("disabled"):
                next_ids = step.get("next_steps", [])
                queue.extend(next_ids)
                continue

            # Skip already-completed steps (from rerun) — just queue next steps
            if step.get("status") == PipelineStatusType.Completed:
                output = "".join(str(o.get("value", "")) for o in step.get("outputs", []))
                next_ids = _get_next_steps(step, output)
                broadcast("step_complete", {
                    "run_id": run_id, "step_id": current_id,
                    "output": output[:500],
                    "cost": step.get("call_cost", []),
                })
                if len(next_ids) > 1:
                    await _run_parallel_branch(pl_run, next_ids, steps_by_id, visited, queue, sem, run_id)
                else:
                    queue.extend(next_ids)
                upsert("pipeline_runs", pl_run)
                continue

            _snapshot_step_history(step)

            # Update step status and persist so polling sees Running
            step["status"] = PipelineStatusType.Running
            pl_run["current_step"] = steps.index(step) if step in steps else 0
            upsert("pipeline_runs", pl_run)
            broadcast("step_start", {"run_id": run_id, "step_id": current_id, "name": step.get("name", "")})

            # Load tool
            tool_id = step.get("tool_id", "")
            tool = step.get("tool") or {}
            if tool_id and not tool:
                tool_data = get_by_id("tools", tool_id)
                if tool_data:
                    tool = tool_data
                    step["tool"] = tool

            tool_type = tool.get("type", ToolType.LLM)
            run_log(run_id, "pipeline", f"Starting step: {step.get('name', '')}",
                    step_id=current_id, detail={"tool_type": str(tool_type)})

            # Handle Parallel node: pass-through, just fan out
            if tool_type == ToolType.Parallel:
                step["status"] = PipelineStatusType.Completed
                broadcast("step_complete", {"run_id": run_id, "step_id": current_id, "output": "parallel"})
                next_ids = step.get("next_steps", [])
                await _run_parallel_branch(pl_run, next_ids, steps_by_id, visited, queue, sem, run_id)
                continue

            # Normal step execution (with retry support)
            retry_enabled = step.get("retry_enabled", False)
            max_retries = step.get("max_retries", 1) if retry_enabled else 0
            attempt = 0
            step_succeeded = False

            while True:
                try:
                    output, agent_output, iteration_outputs = await _execute_step(pl_run, step, tool, sem)

                    # Check stop immediately after step execution
                    if run_id in stop_commands:
                        step["status"] = PipelineStatusType.Failed
                        step["status_text"] = "Stopped by user"
                        pl_run["status"] = PipelineStatusType.Failed
                        run_log(run_id, "pipeline", f"Step stopped: {step.get('name', '')}", step_id=current_id, level="warn")
                        upsert("pipeline_runs", pl_run)
                        break

                    if step.get("_start_outputs"):
                        step["outputs"] = step.pop("_start_outputs")
                    else:
                        step["outputs"] = [{"name": step.get("name", ""), "value": output}]
                    if agent_output is not None:
                        step["outputs"].append({"name": step.get("name", "") + "_agent", "value": agent_output})
                    # Output validation
                    if step.get("validation_enabled"):
                        broadcast("step_validating", {"run_id": run_id, "step_id": current_id})
                        passed, reason, v_usage = await _validate_step_output(step, output, pl_run)
                        if v_usage:
                            v_model = step.get("validation_model", "") or pl_run.get("validation_model", "") or pl_run.get("pipeline_snapshot", {}).get("validation_model", "") or "claude-haiku-4-5-20251001"
                            step.setdefault("call_cost", []).append({
                                "detail": "validation",
                                "model": v_model,
                                "input_token_count": v_usage.get("input_tokens", 0),
                                "output_token_count": v_usage.get("output_tokens", 0),
                            })
                        if not passed:
                            step["status"] = PipelineStatusType.Failed
                            step["status_text"] = f"Validation failed: {reason}"
                            broadcast("step_error", {"run_id": run_id, "step_id": current_id,
                                                     "error": f"Validation failed: {reason}",
                                                     "cost": step.get("call_cost", [])})
                            run_log(run_id, "pipeline",
                                    f"Step validation failed: {step.get('name', '')} - {reason}",
                                    step_id=current_id, level="error")
                            pl_run["status"] = PipelineStatusType.Failed
                            upsert("pipeline_runs", pl_run)
                            break

                    step["status"] = PipelineStatusType.Completed
                    step["status_text"] = ""

                    split_count = len(iteration_outputs) if len(iteration_outputs) > 1 else 0
                    if split_count:
                        step["split_count"] = split_count
                        step["iteration_outputs"] = iteration_outputs

                    evt: dict = {
                        "run_id": run_id,
                        "step_id": current_id,
                        "output": output[:500],
                        "agent_output": agent_output[:500] if agent_output else None,
                        "cost": step.get("call_cost", []),
                        "prompt_used": step.get("prompt_used"),
                    }
                    if step.get("artifacts"):
                        evt["artifacts"] = step["artifacts"]
                    if split_count:
                        evt["split_count"] = split_count
                        evt["iteration_outputs"] = iteration_outputs
                    if step.get("resolved_inputs"):
                        evt["resolved_inputs"] = step["resolved_inputs"]
                    if attempt > 0:
                        evt["retry_attempt"] = attempt
                    broadcast("step_complete", evt)

                    step_succeeded = True
                    break

                except Exception as e:
                    attempt += 1
                    if attempt <= max_retries:
                        run_log(run_id, "pipeline",
                                f"Step failed: {step.get('name', '')} - {e}. Retrying ({attempt}/{max_retries})...",
                                step_id=current_id, level="warn")
                        broadcast("step_retry", {
                            "run_id": run_id, "step_id": current_id,
                            "error": str(e), "attempt": attempt, "max_retries": max_retries,
                        })
                        step["status_text"] = f"Retry {attempt}/{max_retries}: {e}"
                        upsert("pipeline_runs", pl_run)
                        await asyncio.sleep(2 * attempt)  # simple backoff
                        continue

                    step["status"] = PipelineStatusType.Failed
                    step["status_text"] = str(e)
                    broadcast("step_error", {"run_id": run_id, "step_id": current_id, "error": str(e)})
                    run_log(run_id, "pipeline", f"Step failed: {step.get('name', '')} - {e}",
                            step_id=current_id, level="error")
                    traceback.print_exc()
                    pl_run["status"] = PipelineStatusType.Failed
                    upsert("pipeline_runs", pl_run)
                    break

            if not step_succeeded:
                break

            # Pause after this step if requested
            if step.get("pause_after"):
                pl_run["status"] = PipelineStatusType.Paused
                upsert("pipeline_runs", pl_run)
                broadcast("pipeline_paused", {"run_id": run_id, "step_id": current_id})
                break

            # Determine next steps - run concurrently when branching
            next_ids = _get_next_steps(step, output)

            # Loop support: clear visited for downstream steps so they re-execute
            if tool_type == ToolType.LoopCounter and not step.get("_loop_halted"):
                _clear_loop_visited(steps_by_id, visited, next_ids, current_id)
                visited.discard(current_id)  # allow self to re-execute on next pass
                step["status"] = PipelineStatusType.Pending  # reset so LC re-executes

            if len(next_ids) > 1:
                await _run_parallel_branch(pl_run, next_ids, steps_by_id, visited, queue, sem, run_id)
            else:
                queue.extend(next_ids)

            # Save progress
            upsert("pipeline_runs", pl_run)

        # Collect final outputs
        final_outputs = []
        for step in steps:
            for out in step.get("outputs", []):
                final_outputs.append(out)
        pl_run["outputs"] = final_outputs

        if pl_run.get("status") not in (PipelineStatusType.Failed, PipelineStatusType.Paused, PipelineStatusType.WaitingForInput):
            pl_run["status"] = PipelineStatusType.Completed

    except Exception as e:
        pl_run["status"] = PipelineStatusType.Failed
        run_log(run_id, "pipeline", f"Pipeline failed with error: {e}", level="error")
        traceback.print_exc()
    finally:
        # Save all long-term memories at end of run
        for mem in pl_run.get("memories", []):
            if mem.get("type") == "long_term" and mem.get("messages"):
                _save_long_term_memory(pl_run.get("pipeline_id", ""), mem)

        status = pl_run["status"]
        status_name = status.name if hasattr(status, 'name') else str(status)
        run_log(run_id, "pipeline", f"Pipeline finished with status: {status_name}")
        pl_run["completed_at"] = now_iso()
        flush_to_run(run_id, pl_run)
        stop_commands.discard(run_id)
        upsert("pipeline_runs", pl_run)
        broadcast("pipeline_complete", {
            "run_id": run_id,
            "status": pl_run["status"],
        })


async def _run_single_step(pl_run: dict, step: dict, sem: asyncio.Semaphore, run_id: str):
    """Helper for parallel step execution."""
    tool_id = step.get("tool_id", "")
    tool = step.get("tool") or {}
    if tool_id and not tool:
        tool_data = get_by_id("tools", tool_id)
        if tool_data:
            tool = tool_data
            step["tool"] = tool

    _snapshot_step_history(step)

    step["status"] = PipelineStatusType.Running
    upsert("pipeline_runs", pl_run)
    broadcast("step_start", {"run_id": run_id, "step_id": step["id"], "name": step.get("name", "")})

    retry_enabled = step.get("retry_enabled", False)
    max_retries = step.get("max_retries", 1) if retry_enabled else 0
    attempt = 0

    while True:
        try:
            output, agent_output, iteration_outputs = await _execute_step(pl_run, step, tool, sem)

            # Check stop immediately after step execution
            if run_id in stop_commands:
                step["status"] = PipelineStatusType.Failed
                step["status_text"] = "Stopped by user"
                return

            if step.get("_start_outputs"):
                step["outputs"] = step.pop("_start_outputs")
            else:
                step["outputs"] = [{"name": step.get("name", ""), "value": output}]
            if agent_output is not None:
                step["outputs"].append({"name": step.get("name", "") + "_agent", "value": agent_output})

            # Output validation
            if step.get("validation_enabled"):
                broadcast("step_validating", {"run_id": run_id, "step_id": step["id"]})
                passed, reason, v_usage = await _validate_step_output(step, output, pl_run)
                if v_usage:
                    v_model = step.get("validation_model", "") or pl_run.get("validation_model", "") or pl_run.get("pipeline_snapshot", {}).get("validation_model", "") or "claude-haiku-4-5-20251001"
                    step.setdefault("call_cost", []).append({
                        "detail": "validation",
                        "model": v_model,
                        "input_token_count": v_usage.get("input_tokens", 0),
                        "output_token_count": v_usage.get("output_tokens", 0),
                    })
                if not passed:
                    step["status"] = PipelineStatusType.Failed
                    step["status_text"] = f"Validation failed: {reason}"
                    broadcast("step_error", {"run_id": run_id, "step_id": step["id"],
                                             "error": f"Validation failed: {reason}",
                                             "cost": step.get("call_cost", [])})
                    break

            step["status"] = PipelineStatusType.Completed
            step["status_text"] = ""

            split_count = len(iteration_outputs) if len(iteration_outputs) > 1 else 0
            if split_count:
                step["split_count"] = split_count
                step["iteration_outputs"] = iteration_outputs

            evt: dict = {
                "run_id": run_id,
                "step_id": step["id"],
                "output": output[:500],
                "agent_output": agent_output[:500] if agent_output else None,
                "cost": step.get("call_cost", []),
                "prompt_used": step.get("prompt_used"),
            }
            if step.get("artifacts"):
                evt["artifacts"] = step["artifacts"]
            if split_count:
                evt["split_count"] = split_count
                evt["iteration_outputs"] = iteration_outputs
            if step.get("resolved_inputs"):
                evt["resolved_inputs"] = step["resolved_inputs"]
            if attempt > 0:
                evt["retry_attempt"] = attempt
            broadcast("step_complete", evt)
            break

        except Exception as e:
            attempt += 1
            if attempt <= max_retries:
                run_log(run_id, "pipeline",
                        f"Step failed: {step.get('name', '')} - {e}. Retrying ({attempt}/{max_retries})...",
                        step_id=step["id"], level="warn")
                broadcast("step_retry", {
                    "run_id": run_id, "step_id": step["id"],
                    "error": str(e), "attempt": attempt, "max_retries": max_retries,
                })
                step["status_text"] = f"Retry {attempt}/{max_retries}: {e}"
                upsert("pipeline_runs", pl_run)
                await asyncio.sleep(2 * attempt)
                continue

            step["status"] = PipelineStatusType.Failed
            step["status_text"] = str(e)
            broadcast("step_error", {"run_id": run_id, "step_id": step["id"], "error": str(e)})
            break
