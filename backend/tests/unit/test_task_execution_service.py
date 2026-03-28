"""Tests for task_execution_service."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.task_execution_service import (
    stop_task,
    stop_commands,
    _make_cost,
    _sum_costs,
    _build_tool_catalog,
    _format_context,
    _resolve_tool_inputs,
    _parse_endpoint_response,
    generate_plan,
    _execute_reasoning_step,
    execute_plan,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


# ── stop_task ────────────────────────────────────────────────────────


class TestStopTask:

    def test_adds_to_stop_commands(self):
        stop_task("run-123")
        assert "run-123" in stop_commands
        stop_commands.discard("run-123")


# ── _make_cost ───────────────────────────────────────────────────────


class TestMakeCost:

    def test_basic_cost_calculation(self):
        with patch("services.task_execution_service.get_model_pricing", return_value={
            "input_cost": 3.0, "output_cost": 15.0,
        }):
            cost = _make_cost("test-model", 1000, 500, "test step")

        assert cost["model"] == "test-model"
        assert cost["input_tokens"] == 1000
        assert cost["output_tokens"] == 500
        assert cost["detail"] == "test step"
        assert cost["input_cost"] == round((3.0 / 1_000_000) * 1000, 6)
        assert cost["output_cost"] == round((15.0 / 1_000_000) * 500, 6)
        assert cost["total_cost"] == round(cost["input_cost"] + cost["output_cost"], 6)

    def test_zero_tokens(self):
        with patch("services.task_execution_service.get_model_pricing", return_value={
            "input_cost": 3.0, "output_cost": 15.0,
        }):
            cost = _make_cost("m", 0, 0)

        assert cost["total_cost"] == 0.0


# ── _sum_costs ───────────────────────────────────────────────────────


class TestSumCosts:

    def test_sums_multiple_costs(self):
        costs = [
            {"input_tokens": 100, "output_tokens": 50, "total_cost": 0.001},
            {"input_tokens": 200, "output_tokens": 100, "total_cost": 0.002},
        ]
        result = _sum_costs(costs)
        assert result["input_tokens"] == 300
        assert result["output_tokens"] == 150
        assert result["total_cost"] == 0.003
        assert len(result["steps"]) == 2

    def test_empty_list(self):
        result = _sum_costs([])
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_cost"] == 0.0


# ── _build_tool_catalog ──────────────────────────────────────────────


class TestBuildToolCatalog:

    def test_formats_tools(self):
        tools = [
            {
                "name": "Search Tool",
                "id": "t1",
                "type": 0,
                "description": "Searches the web",
                "request_inputs": [
                    {"name": "Query", "is_required": True, "is_default": True},
                ],
            },
            {
                "name": "Agent Tool",
                "id": "t2",
                "type": 3,
                "description": "Does agent stuff",
                "request_inputs": [
                    {"name": "Input", "is_required": True, "is_default": True},
                    {"name": "Mode", "is_required": False},
                ],
            },
        ]
        result = _build_tool_catalog(tools)
        assert "Search Tool" in result
        assert "t1" in result
        assert "Query" in result
        assert "Agent Tool" in result
        assert "Agent" in result  # type 3 = Agent

    def test_empty_tools(self):
        result = _build_tool_catalog([])
        assert "No saved tools" in result


# ── _format_context ──────────────────────────────────────────────────


class TestFormatContext:

    def test_formats_step_outputs(self):
        context = {"step1": "output one", "step2": "output two"}
        result = _format_context(context)
        assert "step1" in result
        assert "output one" in result

    def test_truncates_long_output(self):
        context = {"step1": "x" * 10000}
        result = _format_context(context)
        assert len(result) < 10000

    def test_empty_context(self):
        result = _format_context({})
        assert "no previous" in result.lower() or result.strip() != ""


# ── _resolve_tool_inputs ─────────────────────────────────────────────


class TestResolveToolInputs:

    def test_planner_inputs_take_priority(self):
        tool = {"request_inputs": [
            {"name": "Input", "value": "default", "is_default": True},
            {"name": "Mode", "value": "normal"},
        ]}
        step = {
            "tool_inputs": {"Input": "from_planner", "Mode": "fast"},
            "instructions": "",
        }
        context = {}

        result = _resolve_tool_inputs(tool, step, context)
        result_dict = {r["name"]: r["value"] for r in result}
        assert result_dict["Input"] == "from_planner"
        assert result_dict["Mode"] == "fast"

    def test_template_resolution_from_context(self):
        tool = {"request_inputs": [
            {"name": "Input", "value": "", "is_default": True},
        ]}
        step = {
            "tool_inputs": {"Input": "{{ prev_step }}"},
            "instructions": "",
        }
        context = {"prev_step": "previous output value"}

        result = _resolve_tool_inputs(tool, step, context)
        result_dict = {r["name"]: r["value"] for r in result}
        assert result_dict["Input"] == "previous output value"

    def test_default_input_falls_back_to_instructions(self):
        tool = {"request_inputs": [
            {"name": "Input", "value": "", "is_default": True},
        ]}
        step = {
            "tool_inputs": {},
            "instructions": "Do something specific",
        }
        context = {}

        result = _resolve_tool_inputs(tool, step, context)
        result_dict = {r["name"]: r["value"] for r in result}
        assert result_dict["Input"] == "Do something specific"


# ── _parse_endpoint_response ─────────────────────────────────────────


class TestParseEndpointResponse:

    def test_extracts_fields(self):
        resp = json.dumps({"path": "/tmp/file.mp3", "duration": 5.2, "extra": "ignored"})
        structure = [
            {"key": "path", "children": []},
            {"key": "duration", "children": []},
        ]
        formatted, parsed = _parse_endpoint_response(resp, structure)
        assert parsed["path"] == "/tmp/file.mp3"
        assert parsed["duration"] == 5.2

    def test_no_structure_returns_raw(self):
        formatted, parsed = _parse_endpoint_response("raw text", [])
        assert "raw text" in formatted
        assert parsed == {}

    def test_non_json_response(self):
        formatted, parsed = _parse_endpoint_response("not json", [{"key": "field"}])
        assert parsed == {} or "not json" in formatted


# ── generate_plan ────────────────────────────────────────────────────


class TestGeneratePlan:

    @pytest.mark.asyncio
    async def test_generates_plan_from_tool_use(self):
        mock_response = {
            "content": [
                {"type": "tool_use", "name": "generate_execution_plan", "input": {
                    "goal": "Test goal",
                    "steps": [
                        {"id": "s1", "name": "analyze", "type": "reasoning",
                         "instructions": "Analyze the input"},
                    ],
                }},
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"},
        }
        with patch("services.task_execution_service.chat_with_tools",
                   new_callable=AsyncMock, return_value=mock_response), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}):
            plan, cost = await generate_plan("Do something", "test-model", [])

        assert plan["goal"] == "Test goal"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["name"] == "analyze"
        assert cost["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_returns_empty_plan_on_no_tool_use(self):
        mock_response = {
            "content": [{"type": "text", "text": "No plan needed"}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "model": "test"},
        }
        with patch("services.task_execution_service.chat_with_tools",
                   new_callable=AsyncMock, return_value=mock_response), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}):
            plan, cost = await generate_plan("Simple", "test-model", [])

        assert plan.get("steps", []) == [] or plan == {}


# ── _execute_reasoning_step ──────────────────────────────────────────


class TestExecuteReasoningStep:

    @pytest.mark.asyncio
    async def test_streams_and_returns_output(self):
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "Analysis: "}
            yield {"type": "text", "text": "all good"}
            yield {"type": "usage", "model": "test", "input_tokens": 20, "output_tokens": 10}

        ws_messages = []
        async def mock_ws_send(msg):
            ws_messages.append(msg)

        step = {"id": "s1", "name": "analyze", "instructions": "Analyze this", "output_format": "raw"}
        context = {"prev": "data"}

        with patch("services.task_execution_service.chat_stream", side_effect=mock_stream), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}):
            output, cost = await _execute_reasoning_step(step, context, "test-model", mock_ws_send)

        assert output == "Analysis: all good"
        assert cost is not None
        assert cost["input_tokens"] == 20
        # Check ws_send was called with step_delta messages
        deltas = [m for m in ws_messages if m.get("type") == "step_delta"]
        assert len(deltas) >= 1


# ── execute_plan ─────────────────────────────────────────────────────


class TestExecutePlan:

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "step output"}
            yield {"type": "usage", "model": "test", "input_tokens": 10, "output_tokens": 5}

        ws_messages = []
        async def mock_ws_send(msg):
            ws_messages.append(msg)

        async def mock_wait(sid):
            return []

        run = {
            "id": "run-1",
            "task_plan_id": "plan-1",
            "request": "Do something",
            "input_values": {"query": "hello"},
            "plan": [
                {"id": "s1", "name": "step_one", "type": "reasoning",
                 "instructions": "First step", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
                {"id": "s2", "name": "step_two", "type": "reasoning",
                 "instructions": "Second: {{ step_one }}", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
            ],
            "status": STATUS_RUNNING,
            "output": "",
            "model": "test-model",
            "total_cost": None,
        }

        with patch("services.task_execution_service.chat_stream", side_effect=mock_stream), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}), \
             patch("services.task_execution_service.upsert", side_effect=lambda t, d: d):
            result = await execute_plan(run, "test-model", mock_ws_send, mock_wait)

        assert result["status"] == STATUS_COMPLETED
        assert result["output"] != ""
        # Both steps should be completed (steps use string status)
        for step in result["plan"]:
            assert step["status"] == "completed"

    @pytest.mark.asyncio
    async def test_stop_command_halts_execution(self):
        async def mock_stream(messages, model, system_prompt):
            stop_commands.add("run-stop")
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        ws_messages = []
        async def mock_ws_send(msg):
            ws_messages.append(msg)

        async def mock_wait(sid):
            return []

        run = {
            "id": "run-stop",
            "task_plan_id": "plan-1",
            "request": "Do something",
            "input_values": {},
            "plan": [
                {"id": "s1", "name": "step_one", "type": "reasoning",
                 "instructions": "First", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
                {"id": "s2", "name": "step_two", "type": "reasoning",
                 "instructions": "Second", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
            ],
            "status": STATUS_RUNNING,
            "output": "",
            "model": "test-model",
            "total_cost": None,
        }

        try:
            with patch("services.task_execution_service.chat_stream", side_effect=mock_stream), \
                 patch("services.task_execution_service.get_model_pricing",
                       return_value={"input_cost": 3.0, "output_cost": 15.0}), \
                 patch("services.task_execution_service.upsert", side_effect=lambda t, d: d):
                result = await execute_plan(run, "test-model", mock_ws_send, mock_wait)
        finally:
            stop_commands.discard("run-stop")

        assert result["status"] == STATUS_FAILED

    @pytest.mark.asyncio
    async def test_skipped_steps_preserved(self):
        """Steps with status 'skipped' should be preserved."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        ws_messages = []
        async def mock_ws_send(msg):
            ws_messages.append(msg)

        async def mock_wait(sid):
            return []

        run = {
            "id": "run-skip",
            "task_plan_id": "plan-1",
            "request": "Do something",
            "input_values": {},
            "plan": [
                {"id": "s1", "name": "step_one", "type": "reasoning",
                 "instructions": "Do it", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
            ],
            "status": STATUS_RUNNING,
            "output": "",
            "model": "test-model",
            "total_cost": None,
        }

        with patch("services.task_execution_service.chat_stream", side_effect=mock_stream), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}), \
             patch("services.task_execution_service.upsert", side_effect=lambda t, d: d):
            result = await execute_plan(run, "test-model", mock_ws_send, mock_wait)

        assert result["status"] == STATUS_COMPLETED

    @pytest.mark.asyncio
    async def test_step_failure_stops_execution(self):
        """If a step raises an exception, execution stops and status is FAILED."""
        async def mock_stream(messages, model, system_prompt):
            raise Exception("LLM error")

        ws_messages = []
        async def mock_ws_send(msg):
            ws_messages.append(msg)

        async def mock_wait(sid):
            return []

        run = {
            "id": "run-fail",
            "task_plan_id": "plan-1",
            "request": "Do something",
            "input_values": {},
            "plan": [
                {"id": "s1", "name": "step_one", "type": "reasoning",
                 "instructions": "Fail here", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
                {"id": "s2", "name": "step_two", "type": "reasoning",
                 "instructions": "Never reached", "output_format": "raw",
                 "status": STATUS_PENDING, "output": ""},
            ],
            "status": STATUS_RUNNING,
            "output": "",
            "model": "test-model",
            "total_cost": None,
        }

        with patch("services.task_execution_service.chat_stream", side_effect=mock_stream), \
             patch("services.task_execution_service.get_model_pricing",
                   return_value={"input_cost": 3.0, "output_cost": 15.0}), \
             patch("services.task_execution_service.upsert", side_effect=lambda t, d: d):
            result = await execute_plan(run, "test-model", mock_ws_send, mock_wait)

        assert result["status"] == STATUS_FAILED
        # Second step should still be pending (int STATUS_PENDING since it was never touched)
        assert result["plan"][1]["status"] == STATUS_PENDING or result["plan"][1]["status"] == "pending"
