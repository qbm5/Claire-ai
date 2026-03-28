import json
import asyncio
import copy
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File
from database import get_all, get_by_id, upsert, delete_by_id, get_uid, now_iso
from services.pipeline_engine import run_pipeline, stop_pipeline, build_rerun, submit_user_response
from services.llm import chat_stream_with_tools, chat_with_tools
from api.auth_deps import CurrentUser, get_current_user, check_permission, require_permission, check_resource_access, get_accessible_resource_ids, ws_get_current_user
from config import TOOL_RUNS_PIPELINE_ID
from models.enums import PipelineStatusType

router = APIRouter()


# ── Pipeline AI Assist ───────────────────────────────────────────────

PIPELINE_AI_ASSIST_SYSTEM_PROMPT = r"""You are a pipeline builder for an AI orchestration platform. Given a description, generate a complete pipeline configuration by calling `generate_pipeline_config`.

## Architecture

A pipeline is a directed graph of **steps** connected by **edges**. Each step contains an embedded **tool** that defines what it does. Steps execute in topological order — a step runs only after all its incoming edges have delivered output.

## Step Types

Every step has a `tool_type` field. Set it to one of these integers:

### Core Processing Steps

- **0 = LLM** (tool_id: "-1"): Claude processes a prompt and returns text. The workhorse step type.
  - Fields: `prompt` (with {{Variable}} templates), `system_prompt`, `model`, `response_structure`
  - Use for: analysis, planning, writing, summarization, transformation, decision-making
  - The prompt can reference pipeline inputs and previous step outputs via {{VariableName}}

- **1 = Endpoint** (tool_id: "-2"): Makes an HTTP request to an external API.
  - Fields: `endpoint_url`, `endpoint_method` (0=GET,1=POST,2=PUT,3=DELETE), `endpoint_headers`, `endpoint_body`, `endpoint_query`
  - Headers/body/query are JSON strings of [{key,value}] arrays, e.g. `[{"key":"Content-Type","value":"application/json"}]`
  - URL and values support {{Variable}} templates

- **3 = Agent** (tool_id: "-10"): Runs an agentic loop where Claude calls Python functions as tools.
  - Fields: `prompt`, `system_prompt`, `model`, `agent_functions`, `pip_dependencies`
  - Best for: file operations, code execution, external API calls, multi-step tasks
  - When referencing a saved Agent tool, use its UUID as tool_id instead of "-10"

### Flow Control Steps

- **5 = If** (tool_id: "-3"): Evaluates a condition using LLM and branches execution.
  - Fields: `prompt` (the condition to evaluate), `system_prompt` (evaluator instructions)
  - MUST have `next_steps_true` AND `next_steps_false` arrays (can be empty)
  - The prompt should be a clear yes/no question, e.g. "Does {{AnalyzeStep}} indicate a database layer is needed?"
  - Edges from If steps use `_true` or `_false` as source_handle
  - If steps should NOT have `next_steps` — only use `next_steps_true` and `next_steps_false`

- **8 = Wait** (tool_id: "-6"): Synchronization barrier. Waits for ALL incoming edges to deliver before proceeding.
  - No special fields needed
  - Use ONLY after **parallel fan-out** (one step with multiple outgoing edges) to rejoin branches
  - NEVER use after an If step — only one If branch executes, so Wait would block forever waiting for the other
  - Must have multiple incoming edges, and ALL of them must fire at runtime
  - Output is pass-through of its input

- **10 = LoopCounter** (tool_id: "-4"): Counts loop iterations and halts when max is exceeded.
  - Fields: `max_passes` (default 5)
  - Use with an If step to create retry/loop patterns: Step -> LoopCounter -> If(check condition) -> true:continue / false:back to Step
  - Prevents infinite loops by enforcing a maximum iteration count

- **7 = End** (tool_id: "-5"): Terminal step. Stops execution on this branch.
  - No special fields
  - Every branch should eventually reach an End step or terminate naturally

### Interactive Steps

- **11 = AskUser** (tool_id: "-7"): Multi-round conversation with the user. Asks clarifying questions and collects answers before proceeding.
  - Fields: `prompt` (context for the LLM to decide what to ask), `system_prompt` (MUST include the JSON response format instructions)
  - The LLM generates questions, the user answers, and the loop continues until the LLM decides it has enough information
  - system_prompt MUST instruct the LLM to respond with JSON: `{"status": "questions", "questions": [...]}` or `{"status": "ready", "summary": "..."}`
  - Question format: `{"id": "q1", "text": "Your question?", "type": "text"}` or `{"type": "choice", "options": ["A", "B"]}`
  - Output is the conversation summary — downstream steps can reference it via {{StepName}}
  - Best for: gathering requirements, clarifying ambiguous requests, getting user preferences before proceeding

- **12 = FileUpload** (tool_id: "-8"): Pauses pipeline and asks user to upload file(s).
  - Fields: `prompt` (message shown to user, e.g. "Please upload the CSV file to process")
  - Output is JSON array of uploaded file paths

- **14 = Task** (tool_id: "-11"): AI-planned multi-step task execution. The LLM generates an execution plan from the request using available tools, then executes each step sequentially.
  - Fields: `prompt` (the request/task description, supports {{Variable}} templates), `model`
  - The AI planner analyzes the request, selects from available saved tools, and creates a step-by-step plan
  - Each task step can be: reasoning (LLM thinking), tool (execute a saved tool), or ask_user
  - Output is the final task result after all steps complete
  - Use for: complex multi-tool workflows where the exact steps aren't known ahead of time

### Auto-created (DO NOT include)

- **9 = Start**: Entry point — auto-created by the system. Do NOT include in your output.

## Template Variables

Use `{{VariableName}}` in prompts. Available variables:
- **Pipeline input names** — e.g. `{{Input}}`, `{{WorkingDirectory}}`, `{{ProjectName}}`
- **Previous step names** — e.g. `{{AnalyzeStep}}` references that step's output text
- **Special**: `{{Input[@]}}` references the immediate previous step's output (useful when step name might change)

## Edge Topology

Edges define execution flow. Each edge has:
- `source`: step ID (use `"__START__"` for edges from the auto-created Start step)
- `target`: step ID
- `source_handle`: output port — `"_source"` for normal steps, `"_true"` or `"_false"` for If steps
- `target_handle`: always `"_target"`

### Parallel fan-out (NOT If branching)
When a non-If step has multiple outgoing edges, ALL targets execute in parallel. Use a Wait step to rejoin parallel branches because all branches will complete.

### If branching (exclusive — only one path fires)
If steps have two output ports: `_true` and `_false`. Only ONE branch executes at runtime based on the condition. Because only one branch fires, you must NEVER rejoin If branches with a Wait step (Wait would deadlock waiting for the branch that never ran). Instead, each If branch should either:
- Continue independently to its own End step, OR
- Both branches converge on the same next step directly (without Wait) — this works because that step simply runs when its single incoming edge delivers

## Step Positioning

Arrange steps left-to-right on the canvas:
- Start step is at x=100, y=250 (auto-created, don't include)
- First step(s) at x=400
- Each subsequent step +300 on x-axis
- Parallel branches: offset on y-axis by ~200 (upper branch lower y, lower branch higher y)
- Keep the graph readable — don't stack steps on top of each other

## Common Pipeline Patterns

### Sequential: Start -> A -> B -> C -> End
Simple chain. Each step's output feeds the next step's prompt.

### Parallel with Wait: Start -> [A, B] -> Wait -> C -> End
Fan out to parallel branches, rejoin with Wait before continuing. Wait is correct here because ALL parallel branches will complete.

### Conditional branching (separate endings): Start -> A -> If -> true:B -> End / false:C -> End
Each branch handles its own path independently. Do NOT use Wait to rejoin If branches.

### Conditional branching (converge): Start -> A -> If -> true:B -> D / false:C -> D -> End
Both branches point to the same next step D. D runs when whichever branch fires delivers its output. No Wait needed — D has two incoming edges but only one will fire, and a step runs as soon as any incoming edge delivers.

### User clarification: Start -> AskUser -> Process -> End
Gather information from user before processing.

### Retry loop: Start -> Action -> LoopCounter -> If(success?) -> true:Continue -> End / false:Action
Retry an action until it succeeds or max iterations exceeded. Note: the false branch loops back, so there is no second branch reaching a shared step — no Wait needed.

### Plan-then-execute: Start -> Analyze -> Plan -> [Implement_A, Implement_B] -> Wait -> Verify -> End
Common for software builders — analyze, plan, implement in parallel, verify. Wait is correct here because Plan fans out (not an If), so ALL branches complete.

## Rules

1. Do NOT include a Start step — it is auto-created
2. Every step MUST have `tool_type` set to the correct integer
3. Every step MUST have `tool_id` set to the corresponding negative string ID or a saved tool UUID
4. Steps connect via edges AND via `next_steps` arrays (both must be consistent)
5. Include an edge from `"__START__"` to your first step(s) with source_handle=`"_source"`
6. If steps MUST use `next_steps_true`/`next_steps_false` (not `next_steps`), with `_true`/`_false` source handles on edges
7. Use descriptive step names — they become {{Variable}} references in downstream prompts
8. LLM step prompts should be detailed: include context, instructions, and reference relevant upstream outputs
9. For Agent steps referencing saved tools, use the tool's UUID as tool_id and set tool_type=3
10. After parallel fan-out (non-If step with multiple outgoing edges), use a Wait step to synchronize before continuing
11. NEVER use Wait after If branches — only one If branch fires at runtime, so Wait would deadlock. Instead, have each branch end independently or converge directly on the next step
12. AskUser steps need a system_prompt with the JSON response format (questions/ready)
13. For complex pipelines, use `guidance` to provide overall context that helps each step understand the big picture
14. Every key returned by response_structure should be a meaningful field the step will output
15. For If steps, write the prompt as a clear evaluable question about the input data
16. A step with multiple incoming edges runs when ANY single incoming edge delivers (not all) — Wait is the exception that requires ALL. This means If branches can safely converge on a shared step without Wait
"""

PIPELINE_CONFIG_SCHEMA = {
    "name": "generate_pipeline_config",
    "description": "Generate a complete pipeline configuration with steps, edges, and inputs.",
    "input_schema": {
        "type": "object",
        "required": ["name", "description", "steps", "edges", "inputs"],
        "properties": {
            "name": {"type": "string", "description": "Pipeline display name"},
            "description": {"type": "string", "description": "What the pipeline does"},
            "tag": {"type": "string", "description": "Category tag"},
            "guidance": {"type": "string", "description": "Overall guidance/instructions for the pipeline execution context"},
            "inputs": {
                "type": "array",
                "description": "Pipeline-level inputs. The first should have is_default=true.",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "integer", "description": "0=Text,1=Number,2=Boolean,3=File"},
                        "is_required": {"type": "boolean"},
                        "is_default": {"type": "boolean"},
                    },
                },
            },
            "steps": {
                "type": "array",
                "description": "Pipeline steps (do NOT include Start step — it is auto-created).",
                "items": {
                    "type": "object",
                    "required": ["id", "name", "tool_type", "tool_id"],
                    "properties": {
                        "id": {"type": "string", "description": "Unique step ID (e.g. 'step_1', 'analyze', 'check_data')"},
                        "name": {"type": "string", "description": "Display name — also used as {{StepName}} template variable for downstream steps"},
                        "tool_type": {"type": "integer", "enum": [0, 1, 3, 5, 7, 8, 10, 11, 12, 14], "description": "0=LLM, 1=Endpoint, 3=Agent, 5=If, 7=End, 8=Wait, 10=LoopCounter, 11=AskUser, 12=FileUpload, 14=Task"},
                        "tool_id": {"type": "string", "description": "'-1'=LLM, '-2'=Endpoint, '-3'=If, '-4'=LoopCounter, '-5'=End, '-6'=Wait, '-7'=AskUser, '-8'=FileUpload, '-10'=Agent, or saved tool UUID"},
                        "prompt": {"type": "string", "description": "Prompt template with {{Variable}} placeholders"},
                        "system_prompt": {"type": "string", "description": "System instructions (required for AskUser — must include JSON response format)"},
                        "model": {"type": "string", "description": "Model ID, empty = system default"},
                        "next_steps": {"type": "array", "items": {"type": "string"}, "description": "Step IDs this connects to (normal flow). Do NOT use for If steps."},
                        "next_steps_true": {"type": "array", "items": {"type": "string"}, "description": "If step only: true branch target step IDs"},
                        "next_steps_false": {"type": "array", "items": {"type": "string"}, "description": "If step only: false branch target step IDs"},
                        "max_passes": {"type": "integer", "description": "LoopCounter only: max iterations before halting (default 5)"},
                        "pos_x": {"type": "number", "description": "Canvas X position"},
                        "pos_y": {"type": "number", "description": "Canvas Y position"},
                        "endpoint_url": {"type": "string"},
                        "endpoint_method": {"type": "integer", "enum": [0, 1, 2, 3]},
                        "endpoint_headers": {"type": "string", "description": "JSON [{key,value}] array"},
                        "endpoint_body": {"type": "string", "description": "JSON [{key,value}] array"},
                        "endpoint_query": {"type": "string", "description": "JSON [{key,value}] array"},
                        "request_inputs": {
                            "type": "array",
                            "description": "Template variables used in this step's prompt",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "integer"},
                                    "is_required": {"type": "boolean"},
                                    "is_default": {"type": "boolean"},
                                },
                            },
                        },
                        "agent_functions": {
                            "type": "array",
                            "description": "Python functions for Agent steps",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "function_string": {"type": "string"},
                                },
                            },
                        },
                        "pip_dependencies": {"type": "array", "items": {"type": "string"}},
                        "response_structure": {
                            "type": "array",
                            "description": "Structured output fields the step produces",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "type": {"type": "string", "enum": ["string", "number", "boolean", "object"]},
                                },
                            },
                        },
                    },
                },
            },
            "edges": {
                "type": "array",
                "description": "Connections between steps. Include edge(s) from '__START__' to your first step(s).",
                "items": {
                    "type": "object",
                    "required": ["source", "target", "source_handle", "target_handle"],
                    "properties": {
                        "source": {"type": "string", "description": "Source step ID. Use '__START__' for edges from the auto-created Start step."},
                        "target": {"type": "string", "description": "Target step ID"},
                        "source_handle": {"type": "string", "description": "'_source' for normal steps, '_true'/'_false' for If steps"},
                        "target_handle": {"type": "string", "description": "Always '_target'"},
                    },
                },
            },
        },
    },
}


CLARIFICATION_SYSTEM_PROMPT = r"""You are a pipeline architect for an AI orchestration platform. Before building a pipeline, you need to ask the user targeted clarifying questions to ensure the best result.

## Your Goal
Analyze the user's pipeline description and generate 3-6 focused questions that will help you build a better pipeline. Your questions should uncover:

1. **Scope & complexity**: How many distinct processing stages are needed? Should it be simple/linear or use advanced patterns?
2. **Data flow**: What are the expected inputs/outputs? Are there intermediate transformations?
3. **Parallelism**: Are there independent tasks that could run in parallel for efficiency?
4. **Conditional logic**: Are there decision points where the pipeline should branch based on results?
5. **User interaction**: Should the pipeline pause for user input/approval at any point?
6. **Error handling**: Should failed steps be retried? How should errors be handled?
7. **External integrations**: Are there APIs, file systems, or databases involved?

## Pipeline Capabilities (inform your questions)
The platform supports these step types:
- **LLM**: Claude processes text (analysis, writing, planning, summarization)
- **Endpoint**: HTTP API calls (GET/POST/PUT/DELETE)
- **Agent**: Python code execution with agentic tool loops
- **If**: Conditional branching (true/false paths)
- **Wait**: Synchronize parallel branches
- **LoopCounter**: Retry/iteration patterns with max limit
- **AskUser**: Multi-round Q&A with the user mid-pipeline
- **FileUpload**: File upload from user
- **End**: Terminal step

## Rules
- Generate 3-6 questions — enough to clarify ambiguity, not so many as to overwhelm
- Make questions specific to the user's description, not generic
- Each question should have a clear purpose that affects pipeline design
- Provide choice options when the answer space is constrained
- If the description is already very detailed and clear, you may generate fewer questions
- Focus on decisions that impact pipeline STRUCTURE (step types, branching, parallelism)
"""

CLARIFICATION_SCHEMA = {
    "name": "generate_clarifying_questions",
    "description": "Generate clarifying questions to ask the user before building the pipeline.",
    "input_schema": {
        "type": "object",
        "required": ["questions"],
        "properties": {
            "questions": {
                "type": "array",
                "description": "3-6 targeted questions about the pipeline requirements",
                "items": {
                    "type": "object",
                    "required": ["id", "text", "type"],
                    "properties": {
                        "id": {"type": "string", "description": "Unique question ID (e.g. 'q1', 'q2')"},
                        "text": {"type": "string", "description": "The question to ask the user"},
                        "type": {"type": "string", "enum": ["text", "choice"], "description": "text=free text, choice=multiple choice"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Options for choice-type questions",
                        },
                    },
                },
            },
        },
    },
}


def _build_pipeline_ai_assist_message(description: str, current_pipeline: dict, available_tools: list) -> str:
    """Build a user message with description, current pipeline state, and available tools."""
    parts = [f"## User Request\n{description}\n"]

    # Show available saved tools
    if available_tools:
        tool_lines = []
        type_names = {0: "LLM", 1: "Endpoint", 3: "Agent"}
        for t in available_tools:
            tt = t.get("type")
            tname = type_names.get(tt, str(tt))
            desc = t.get("description", "")
            desc_str = f": {desc}" if desc else ""
            tool_lines.append(f"- **{t.get('name')}** (id: `{t.get('id')}`, type: {tname}){desc_str}")
        parts.append("## Available Saved Tools\nYou can reference these by their UUID as tool_id (set tool_type to match the tool's type):\n" + "\n".join(tool_lines))

    # Current pipeline context
    ctx = []
    if current_pipeline.get("name"):
        ctx.append(f"Name: {current_pipeline['name']}")
    if current_pipeline.get("description"):
        ctx.append(f"Description: {current_pipeline['description']}")
    if current_pipeline.get("tag"):
        ctx.append(f"Tag: {current_pipeline['tag']}")
    if current_pipeline.get("guidance"):
        ctx.append(f"Guidance: {current_pipeline['guidance'][:300]}")

    inputs = current_pipeline.get("inputs") or []
    if inputs:
        input_details = []
        for i in inputs:
            name = i.get("name", "")
            if not name:
                continue
            type_map = {0: "Text", 1: "Number", 2: "Boolean", 3: "File"}
            itype = type_map.get(i.get("type", 0), "Text")
            req = "required" if i.get("is_required") else "optional"
            default = ", default" if i.get("is_default") else ""
            input_details.append(f"  - {name} ({itype}, {req}{default})")
        if input_details:
            ctx.append("Inputs:\n" + "\n".join(input_details))

    steps = current_pipeline.get("steps") or []
    if steps:
        type_map = {0: "LLM", 1: "Endpoint", 2: "Pause", 3: "Agent", 5: "If", 6: "Parallel",
                    7: "End", 8: "Wait", 9: "Start", 10: "LoopCounter", 11: "AskUser", 12: "FileUpload", 14: "Task"}
        step_details = []
        for s in steps:
            sname = s.get("name", "")
            tool = s.get("tool", {})
            stype = type_map.get(tool.get("type"), "?")
            ns = s.get("next_steps", [])
            ns_str = f" -> {', '.join(ns)}" if ns else ""
            step_details.append(f"  - {sname} ({stype}){ns_str}")
        if step_details:
            ctx.append("Steps:\n" + "\n".join(step_details))

    if ctx:
        parts.append("## Current Pipeline State\n" + "\n".join(ctx))

    parts.append("\nGenerate the complete pipeline configuration by calling `generate_pipeline_config`.")
    return "\n\n".join(parts)


async def ws_ai_assist_pipeline(ws: WebSocket):
    """WebSocket handler for AI-assisted pipeline generation with streaming progress.

    Supports two flows:
    1. Direct generation: phase="generate" (or absent) — generates pipeline immediately
    2. Clarification flow: phase="clarify" — asks questions first, waits for answers, then generates
    """
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
        current_pipeline = data.get("current_pipeline", {})
        phase = data.get("phase", "generate")

        # Load available tools for context
        available_tools = get_all("tools", order_by="sort_index")
        tool_summaries = [
            {"id": t.get("id"), "name": t.get("name"), "type": t.get("type"), "description": t.get("description", "")}
            for t in available_tools if t.get("is_enabled")
        ]

        answers_text = ""

        # ── Phase 1: Clarification (optional) ──────────────────────────
        if phase == "clarify":
            await ws.send_text(json.dumps({"type": "status", "text": "Analyzing your request..."}))

            clarify_message = f"## User's Pipeline Description\n{description}\n"
            if current_pipeline.get("name"):
                clarify_message += f"\nExisting pipeline name: {current_pipeline['name']}"
            if current_pipeline.get("description"):
                clarify_message += f"\nExisting pipeline description: {current_pipeline['description']}"
            if tool_summaries:
                type_names = {0: "LLM", 1: "Endpoint", 3: "Agent"}
                tool_lines = [f"- {t['name']} ({type_names.get(t['type'], '?')}): {t.get('description', '')}" for t in tool_summaries]
                clarify_message += "\n\n## Available Tools\n" + "\n".join(tool_lines)
            clarify_message += "\n\nGenerate clarifying questions to help you build the best pipeline."

            result = await chat_with_tools(
                [{"role": "user", "content": clarify_message}],
                [CLARIFICATION_SCHEMA],
                model,
                CLARIFICATION_SYSTEM_PROMPT,
                tool_choice={"type": "tool", "name": "generate_clarifying_questions"},
            )

            questions = []
            for block in (result.get("content") or []):
                if block.get("type") == "tool_use" and block.get("name") == "generate_clarifying_questions":
                    questions = block.get("input", {}).get("questions", [])
                    break

            if questions:
                await ws.send_text(json.dumps({"type": "questions", "questions": questions}))

                # Wait for answers from the frontend
                answer_raw = await asyncio.wait_for(ws.receive_text(), timeout=600)
                answer_data = json.loads(answer_raw)
                answers = answer_data.get("answers", [])

                # Format answers for the generation prompt
                qa_lines = []
                q_map = {q["id"]: q["text"] for q in questions}
                for a in answers:
                    q_text = q_map.get(a.get("id"), "")
                    qa_lines.append(f"Q: {q_text}\nA: {a.get('answer', '(no answer)')}")
                answers_text = "\n\n".join(qa_lines)

        # ── Phase 2: Generation ─────────────────────────────────────────
        await ws.send_text(json.dumps({"type": "status", "text": "Building pipeline configuration..."}))

        user_message = _build_pipeline_ai_assist_message(description, current_pipeline, tool_summaries)
        if answers_text:
            user_message += f"\n\n## Clarification Q&A\nThe user answered these questions to help refine the pipeline:\n\n{answers_text}\n\nUse these answers to make better design decisions about step types, branching, parallelism, and overall pipeline structure."

        messages = [{"role": "user", "content": user_message}]

        pipeline_config = None
        async for event in chat_stream_with_tools(
            messages,
            [PIPELINE_CONFIG_SCHEMA],
            model,
            PIPELINE_AI_ASSIST_SYSTEM_PROMPT,
            tool_choice={"type": "tool", "name": "generate_pipeline_config"},
        ):
            if event["type"] == "tool_start":
                await ws.send_text(json.dumps({"type": "status", "text": "Generating pipeline configuration..."}))
            elif event["type"] == "input_delta":
                await ws.send_text(json.dumps({"type": "delta", "text": event["partial_json"]}))
            elif event["type"] == "tool_done":
                pipeline_config = event.get("input", {})
            elif event["type"] == "usage":
                await ws.send_text(json.dumps({
                    "type": "result",
                    "pipeline_config": pipeline_config,
                    "usage": event,
                }))

    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        try:
            await ws.send_text(json.dumps({"type": "error", "text": "Timed out waiting for answers"}))
        except Exception:
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
async def list_pipelines(user: CurrentUser = Depends(get_current_user)):
    accessible_ids = get_accessible_resource_ids(user, "pipelines")
    all_pipelines = [p for p in get_all("pipelines", order_by="sort_index") if p.get("id") != TOOL_RUNS_PIPELINE_ID]
    if accessible_ids is None:  # admin
        return all_pipelines
    return [p for p in all_pipelines if p["id"] in accessible_ids]


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str):
    pl = get_by_id("pipelines", pipeline_id)
    if not pl:
        return {"error": "not found"}
    return pl


@router.post("")
async def save_pipeline(pipeline: dict, user: CurrentUser = Depends(get_current_user)):
    existing = get_by_id("pipelines", pipeline.get("id", ""))
    action = "edit" if existing else "create"
    if not check_permission(user, "pipelines", action):
        raise HTTPException(403, "Permission denied")
    pipeline["updated_at"] = now_iso()
    result = upsert("pipelines", pipeline)
    return {"response": result["id"]}


@router.post("/{pipeline_id}/copy")
async def copy_pipeline(pipeline_id: str):
    pl = get_by_id("pipelines", pipeline_id)
    if not pl:
        return {"error": "not found"}
    new_pl = copy.deepcopy(pl)
    new_pl["id"] = get_uid()
    new_pl["name"] = f"{pl['name']} (Copy)"
    new_pl["created_at"] = now_iso()
    new_pl["updated_at"] = now_iso()
    result = upsert("pipelines", new_pl)
    return {"response": result["id"]}


@router.post("/{pipeline_id}/image")
async def upload_pipeline_image(pipeline_id: str, file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    if not check_permission(user, "pipelines", "edit"):
        raise HTTPException(403, "Permission denied")
    pl = get_by_id("pipelines", pipeline_id)
    if not pl:
        raise HTTPException(404, "Pipeline not found")
    from config import AZURE_STORAGE_CONNECTION_STRING
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise HTTPException(400, "AZURE_STORAGE_CONNECTION_STRING is not configured")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 10MB")
    from services.blob_service import resize_and_upload, delete_blob
    old_url = pl.get("image_url", "")
    if old_url:
        delete_blob(old_url)
    image_url = resize_and_upload(file_bytes, file.filename or "image.png")
    pl["image_url"] = image_url
    pl["updated_at"] = now_iso()
    upsert("pipelines", pl)
    return {"image_url": image_url}


@router.delete("/{pipeline_id}/image")
async def delete_pipeline_image(pipeline_id: str, user: CurrentUser = Depends(get_current_user)):
    if not check_permission(user, "pipelines", "edit"):
        raise HTTPException(403, "Permission denied")
    pl = get_by_id("pipelines", pipeline_id)
    if not pl:
        raise HTTPException(404, "Pipeline not found")
    old_url = pl.get("image_url", "")
    if old_url:
        from services.blob_service import delete_blob
        delete_blob(old_url)
    pl["image_url"] = ""
    pl["updated_at"] = now_iso()
    upsert("pipelines", pl)
    return {"response": "ok"}


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, user: CurrentUser = Depends(require_permission("pipelines", "delete"))):
    # Clean up blob image if exists
    pl = get_by_id("pipelines", pipeline_id)
    if pl and pl.get("image_url"):
        from services.blob_service import delete_blob
        delete_blob(pl["image_url"])
    # Delete associated runs first (FK constraint)
    runs = get_all("pipeline_runs", "pipeline_id = ?", (pipeline_id,))
    for r in runs:
        delete_by_id("pipeline_runs", r["id"])
    delete_by_id("pipelines", pipeline_id)
    return {"response": "ok"}


@router.post("/run")
async def start_pipeline_run(pl_run: dict, user: CurrentUser = Depends(get_current_user)):
    """Start a pipeline run. Returns immediately, execution happens in background."""
    pipeline_id = pl_run.get("pipeline_id", "")
    if pipeline_id and not check_resource_access(user, "pipelines", pipeline_id):
        raise HTTPException(403, "Permission denied")
    pl_run["status"] = PipelineStatusType.Running
    pl_run["created_at"] = now_iso()
    pl_run["user_id"] = user.id
    if not pl_run.get("id"):
        pl_run["id"] = get_uid()

    result = upsert("pipeline_runs", pl_run)

    # Run in background
    asyncio.create_task(run_pipeline(result["id"]))

    return result


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    from services.pipeline_logger import get_log_entries
    r = get_by_id("pipeline_runs", run_id)
    if not r:
        return {"error": "not found"}
    # If run is still active, include in-memory log entries
    # (they get flushed to the doc when the run finishes)
    if not r.get("log_entries"):
        live_entries = get_log_entries(run_id)
        if live_entries:
            r["log_entries"] = live_entries
    return r


@router.post("/runs/{run_id}/rerun")
async def rerun_from_step(run_id: str, body: dict, user: CurrentUser = Depends(get_current_user)):
    from_step_id = body.get("from_step_id")
    if not from_step_id:
        return {"error": "from_step_id is required"}

    old_run = get_by_id("pipeline_runs", run_id)
    if not old_run:
        return {"error": "run not found"}

    pipeline = get_by_id("pipelines", old_run["pipeline_id"])
    if not pipeline:
        return {"error": "pipeline not found"}

    new_run = build_rerun(old_run, pipeline, from_step_id)
    new_run["user_id"] = user.id
    upsert("pipeline_runs", new_run)
    asyncio.create_task(run_pipeline(new_run["id"]))
    return new_run


@router.post("/runs/{run_id}/resume")
async def resume_pipeline_run(run_id: str, user: CurrentUser = Depends(get_current_user)):
    """Resume a paused pipeline run from where it left off."""
    run = get_by_id("pipeline_runs", run_id)
    if not run:
        return {"error": "run not found"}
    if run.get("status") != PipelineStatusType.Paused:
        return {"error": "run is not paused"}
    run["status"] = PipelineStatusType.Running
    if not run.get("user_id") or run["user_id"] == "default":
        run["user_id"] = user.id
    upsert("pipeline_runs", run)
    asyncio.create_task(run_pipeline(run["id"]))
    return run


@router.post("/runs/{run_id}/respond")
async def respond_to_step(run_id: str, body: dict):
    step_id = body.get("step_id")
    answers = body.get("answers", [])
    submit_user_response(run_id, step_id, answers)
    return {"response": "ok"}


@router.post("/runs/{run_id}/stop")
async def stop_pipeline_run(run_id: str):
    stop_pipeline(run_id)
    return {"response": "stop requested"}


@router.put("/runs/{run_id}/steps/{step_id}/output")
async def update_step_output(run_id: str, step_id: str, body: dict, user: CurrentUser = Depends(get_current_user)):
    """Update a completed step's output while the run is paused."""
    run = get_by_id("pipeline_runs", run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.get("status") != PipelineStatusType.Paused:
        raise HTTPException(400, "Run must be paused to edit step outputs")
    if not user.is_admin and run.get("user_id", "default") != user.id:
        raise HTTPException(403, "Cannot edit another user's run")

    steps = run.get("steps", [])
    step = next((s for s in steps if s.get("id") == step_id), None)
    if not step:
        raise HTTPException(404, "Step not found")
    if step.get("status") != PipelineStatusType.Completed:
        raise HTTPException(400, "Only completed steps can be edited")

    new_value = body.get("value", "")
    outputs = step.get("outputs", [])
    if outputs:
        outputs[0]["value"] = new_value
    else:
        step["outputs"] = [{"name": step.get("name", ""), "value": new_value}]

    upsert("pipeline_runs", run)
    return {"success": True}


@router.get("/{pipeline_id}/runs")
async def list_runs(pipeline_id: str):
    return get_all("pipeline_runs", "pipeline_id = ?", (pipeline_id,), order_by="created_at DESC")


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    import os, shutil
    from config import UPLOADS_DIR
    delete_by_id("pipeline_runs", run_id)
    upload_dir = os.path.join(UPLOADS_DIR, run_id)
    if os.path.isdir(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)
    return {"response": "ok"}


# ── Long-term memory endpoints ──

@router.get("/{pipeline_id}/memories")
async def list_memories(pipeline_id: str):
    return get_all("pipeline_memories", "pipeline_id = ?", (pipeline_id,))


@router.get("/{pipeline_id}/memories/{memory_node_id}")
async def get_memory(pipeline_id: str, memory_node_id: str):
    results = get_all("pipeline_memories",
        "pipeline_id = ? AND memory_node_id = ?", (pipeline_id, memory_node_id))
    if results:
        return results[0]
    return {"messages": [], "memory_node_id": memory_node_id}


@router.delete("/{pipeline_id}/memories/{memory_node_id}")
async def clear_memory(pipeline_id: str, memory_node_id: str):
    results = get_all("pipeline_memories",
        "pipeline_id = ? AND memory_node_id = ?", (pipeline_id, memory_node_id))
    for r in results:
        delete_by_id("pipeline_memories", r["id"])
    return {"response": "ok"}
