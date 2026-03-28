"""Tests for pipeline_engine pure/near-pure functions."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from models.enums import ToolType, PipelineStatusType
from services.pipeline_engine import (
    _parse_ask_user_response,
    _normalize_questions,
    _get_next_steps,
    build_rerun,
    _get_step_memories,
    _build_memory_messages,
    _append_to_memory,
    submit_user_response,
    stop_pipeline,
    stop_commands,
    _pending_responses,
    _validate_step_output,
    _prep_step,
    _clear_loop_visited,
)


# ── _parse_ask_user_response ────────────────────────────────────────


class TestParseAskUserResponse:

    def test_none_input(self):
        result = _parse_ask_user_response(None)
        assert result == {"status": "ready", "summary": ""}

    def test_empty_string(self):
        result = _parse_ask_user_response("")
        assert result == {"status": "ready", "summary": ""}

    def test_non_string_input(self):
        result = _parse_ask_user_response(123)
        assert result == {"status": "ready", "summary": "123"}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"status": "ready", "summary": "All done"}\n```'
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"
        assert result["summary"] == "All done"

    def test_json_in_plain_fence(self):
        text = '```\n{"status": "questions", "questions": [{"id": "q1", "text": "Why?"}]}\n```'
        result = _parse_ask_user_response(text)
        assert result["status"] == "questions"

    def test_raw_json_object(self):
        text = '{"status": "ready", "summary": "Done"}'
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"

    def test_json_embedded_in_text(self):
        text = 'Here is my response: {"status": "ready", "summary": "ok"} and more text'
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"

    def test_nested_braces_bracket_counting(self):
        text = '{"status": "ready", "data": {"nested": {"deep": true}}, "summary": "done"}'
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"
        assert result["data"]["nested"]["deep"] is True

    def test_plain_text_fallback(self):
        text = "I have no questions, everything is clear."
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"
        assert result["summary"] == text

    def test_invalid_json_in_fence_falls_through(self):
        text = '```json\n{invalid json here}\n```'
        result = _parse_ask_user_response(text)
        # Should fall through to bracket counting or fallback
        assert "status" in result

    def test_string_with_escaped_quotes(self):
        text = '{"status": "ready", "summary": "He said \\"hello\\""}'
        result = _parse_ask_user_response(text)
        assert result["status"] == "ready"


# ── _normalize_questions ────────────────────────────────────────────


class TestNormalizeQuestions:

    def test_valid_questions(self):
        questions = [
            {"id": "q1", "text": "What is your name?", "type": "text"},
            {"id": "q2", "text": "Pick one", "type": "choice", "options": ["A", "B"]},
        ]
        result = _normalize_questions(questions)
        assert len(result) == 2
        assert result[0]["text"] == "What is your name?"
        assert result[1]["type"] == "choice"
        assert result[1]["options"] == ["A", "B"]

    def test_non_list_input(self):
        assert _normalize_questions("not a list") == []
        assert _normalize_questions(None) == []
        assert _normalize_questions(42) == []

    def test_non_dict_items_skipped(self):
        result = _normalize_questions(["not a dict", {"text": "Valid?"}])
        assert len(result) == 1

    def test_questions_without_text_skipped(self):
        result = _normalize_questions([{"id": "q1"}, {"id": "q2", "text": ""}])
        assert len(result) == 0

    def test_invalid_type_falls_back_to_text(self):
        result = _normalize_questions([{"text": "Q?", "type": "dropdown"}])
        assert result[0]["type"] == "text"

    def test_choice_without_options_falls_back_to_text(self):
        result = _normalize_questions([{"text": "Pick", "type": "choice"}])
        assert result[0]["type"] == "text"

    def test_choice_with_empty_options_falls_back_to_text(self):
        result = _normalize_questions([{"text": "Pick", "type": "choice", "options": []}])
        assert result[0]["type"] == "text"

    def test_auto_generated_id(self):
        result = _normalize_questions([{"text": "Question?"}])
        assert result[0]["id"] == "q1"

    def test_alternative_text_keys(self):
        # Tests label and question as fallback text fields
        r1 = _normalize_questions([{"label": "Label text"}])
        assert r1[0]["text"] == "Label text"
        r2 = _normalize_questions([{"question": "Question text"}])
        assert r2[0]["text"] == "Question text"


# ── _get_next_steps ─────────────────────────────────────────────────


class TestGetNextSteps:

    def test_regular_step(self):
        step = {"next_steps": ["s2", "s3"], "tool": {"type": ToolType.LLM}}
        assert _get_next_steps(step, "some output") == ["s2", "s3"]

    def test_if_step_true(self):
        step = {
            "next_steps": [],
            "next_steps_true": ["s_true"],
            "next_steps_false": ["s_false"],
            "tool": {"type": ToolType.If},
        }
        assert _get_next_steps(step, "true") == ["s_true"]
        assert _get_next_steps(step, "1") == ["s_true"]  # "1" matches true
        assert _get_next_steps(step, "yes") == ["s_true"]
        assert _get_next_steps(step, " TRUE ") == ["s_true"]

    def test_if_step_false(self):
        step = {
            "next_steps": [],
            "next_steps_true": ["s_true"],
            "next_steps_false": ["s_false"],
            "tool": {"type": ToolType.If},
        }
        assert _get_next_steps(step, "false") == ["s_false"]
        assert _get_next_steps(step, "no") == ["s_false"]
        assert _get_next_steps(step, "0") == ["s_false"]

    def test_if_step_true_includes_regular_next_steps(self):
        step = {
            "next_steps": ["s_common"],
            "next_steps_true": ["s_true"],
            "next_steps_false": ["s_false"],
            "tool": {"type": ToolType.If},
        }
        result = _get_next_steps(step, "true")
        assert result == ["s_true", "s_common"]

    def test_loop_counter_halted(self):
        step = {
            "next_steps": ["s_next"],
            "_loop_halted": True,
            "tool": {"type": ToolType.LoopCounter},
        }
        assert _get_next_steps(step, "") == []

    def test_loop_counter_not_halted(self):
        step = {
            "next_steps": ["s_next"],
            "_loop_halted": False,
            "tool": {"type": ToolType.LoopCounter},
        }
        assert _get_next_steps(step, "pass") == ["s_next"]

    def test_no_tool(self):
        step = {"next_steps": ["s2"]}
        assert _get_next_steps(step, "output") == ["s2"]


# ── build_rerun ──────────────────────────────────────────────────────


class TestBuildRerun:

    def test_basic_rerun(self):
        pipeline = {
            "steps": [
                {"id": "s1", "name": "Step 1", "is_start": True, "next_steps": ["s2"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s2", "name": "Step 2", "next_steps": ["s3"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s3", "name": "Step 3", "next_steps": [],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
            ],
        }
        old_run = {
            "id": "old-run",
            "pipeline_id": "p1",
            "inputs": [{"name": "Start", "value": "hello"}],
            "steps": [
                {"id": "s1", "outputs": [{"name": "s1", "value": "out1"}], "call_cost": [{"detail": "s1"}],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s2", "outputs": [{"name": "s2", "value": "out2"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s3", "outputs": [{"name": "s3", "value": "out3"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
            ],
        }

        new_run = build_rerun(old_run, pipeline, "s2")

        steps_by_id = {s["id"]: s for s in new_run["steps"]}
        # s1 is before from_step_id → should have outputs copied
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Completed
        assert steps_by_id["s1"]["outputs"] == [{"name": "s1", "value": "out1"}]
        # s2 is from_step_id → should be Pending with no outputs
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Pending
        assert steps_by_id["s2"]["outputs"] == []
        # s3 is after → should also be Pending
        assert steps_by_id["s3"]["status"] == PipelineStatusType.Pending

        assert new_run["status"] == PipelineStatusType.Running
        assert new_run["pipeline_id"] == "p1"
        assert new_run["rerun_from"]["run_id"] == "old-run"
        assert new_run["rerun_from"]["step_id"] == "s2"

    def test_rerun_with_branching(self):
        pipeline = {
            "steps": [
                {"id": "s1", "name": "Start", "is_start": True, "next_steps": ["s2", "s3"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s2", "name": "Branch A", "next_steps": ["s4"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s3", "name": "Branch B", "next_steps": ["s4"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s4", "name": "Merge", "next_steps": [],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
            ],
        }
        old_run = {
            "id": "old-run", "pipeline_id": "p1", "inputs": [],
            "steps": [
                {"id": "s1", "outputs": [{"name": "s1", "value": "o1"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s2", "outputs": [{"name": "s2", "value": "o2"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s3", "outputs": [{"name": "s3", "value": "o3"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s4", "outputs": [{"name": "s4", "value": "o4"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
            ],
        }

        new_run = build_rerun(old_run, pipeline, "s3")
        steps_by_id = {s["id"]: s for s in new_run["steps"]}
        # s1 and s2 are before s3 → completed
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Completed
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Completed
        # s3 is the rerun point → pending
        assert steps_by_id["s3"]["status"] == PipelineStatusType.Pending
        # s4 is reachable from s1→s2→s4 (before s3) so it's also completed
        assert steps_by_id["s4"]["status"] == PipelineStatusType.Completed

    def test_rerun_no_explicit_start(self):
        """When no is_start flag, first step used as start."""
        pipeline = {
            "steps": [
                {"id": "s1", "name": "First", "next_steps": ["s2"],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
                {"id": "s2", "name": "Second", "next_steps": [],
                 "inputs": [], "next_steps_true": [], "next_steps_false": []},
            ],
        }
        old_run = {
            "id": "old", "pipeline_id": "p1", "inputs": [],
            "steps": [
                {"id": "s1", "outputs": [{"name": "s1", "value": "v"}], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
                {"id": "s2", "outputs": [], "call_cost": [],
                 "tool_outputs": [], "iteration_outputs": [], "split_count": 0},
            ],
        }
        new_run = build_rerun(old_run, pipeline, "s2")
        steps_by_id = {s["id"]: s for s in new_run["steps"]}
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Completed
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Pending


# ── Memory helpers ───────────────────────────────────────────────────


class TestMemoryHelpers:

    def test_get_step_memories(self):
        pipeline_run = {
            "pipeline_snapshot": {
                "edges": [
                    {"source": "step1", "source_handle": "right_memory", "target": "mem1"},
                    {"source": "step1", "source_handle": "right", "target": "step2"},
                    {"source": "step2", "source_handle": "bottom_memory", "target": "mem2"},
                ],
            },
            "memories": [
                {"id": "mem1", "messages": []},
                {"id": "mem2", "messages": []},
            ],
        }
        result = _get_step_memories(pipeline_run, "step1")
        assert len(result) == 1
        assert result[0]["id"] == "mem1"

    def test_get_step_memories_no_matches(self):
        pipeline_run = {
            "pipeline_snapshot": {"edges": []},
            "memories": [],
        }
        assert _get_step_memories(pipeline_run, "step1") == []

    def test_build_memory_messages(self):
        memories = [
            {"messages": [
                {"role": "user", "content": "hello", "timestamp": "2024-01-01T00:00:01"},
                {"role": "assistant", "content": "hi", "timestamp": "2024-01-01T00:00:02"},
            ]},
            {"messages": [
                {"role": "user", "content": "earlier", "timestamp": "2024-01-01T00:00:00"},
            ]},
        ]
        result = _build_memory_messages(memories)
        assert len(result) == 3
        # Should be sorted by timestamp
        assert result[0]["content"] == "earlier"
        assert result[1]["content"] == "hello"
        assert result[2]["content"] == "hi"

    def test_build_memory_messages_empty(self):
        assert _build_memory_messages([]) == []
        assert _build_memory_messages([{"messages": []}]) == []

    def test_append_to_memory(self):
        pipeline_run = {}
        memory = {"messages": [], "max_messages": 0}
        _append_to_memory(pipeline_run, memory, "user msg", "assistant msg", "Step1")
        assert len(memory["messages"]) == 2
        assert memory["messages"][0]["role"] == "user"
        assert memory["messages"][0]["content"] == "user msg"
        assert memory["messages"][1]["role"] == "assistant"
        assert memory["messages"][1]["content"] == "assistant msg"

    def test_append_to_memory_trims_at_max(self):
        memory = {
            "messages": [
                {"role": "user", "content": "old1", "step_name": "s", "timestamp": "t"},
                {"role": "assistant", "content": "old2", "step_name": "s", "timestamp": "t"},
            ],
            "max_messages": 2,
        }
        _append_to_memory({}, memory, "new_u", "new_a", "s")
        # max_messages=2 means 4 messages max (2*2), we have 4 so no trim yet
        assert len(memory["messages"]) == 4

        _append_to_memory({}, memory, "newest_u", "newest_a", "s")
        # Now 6 > 4, should trim to last 4
        assert len(memory["messages"]) == 4
        assert memory["messages"][0]["content"] == "new_u"


# ── submit_user_response / stop_pipeline ─────────────────────────────


class TestSubmitAndStop:

    def test_submit_user_response_existing_key(self):
        event = asyncio.Event()
        key = ("run1", "step1")
        _pending_responses[key] = {"event": event, "answers": None}
        try:
            submit_user_response("run1", "step1", [{"id": "q1", "answer": "yes"}])
            assert _pending_responses[key]["answers"] == [{"id": "q1", "answer": "yes"}]
            assert event.is_set()
        finally:
            _pending_responses.pop(key, None)

    def test_submit_user_response_nonexistent_key(self):
        # Should be a no-op, not raise
        submit_user_response("nonexistent", "step", [])

    def test_stop_pipeline(self):
        stop_pipeline("run-xyz")
        assert "run-xyz" in stop_commands
        stop_commands.discard("run-xyz")


# ── _validate_step_output ────────────────────────────────────────────


class TestValidateStepOutput:

    @pytest.mark.asyncio
    async def test_validation_passes(self):
        mock_response = ('{"passed": true, "reason": "Looks good"}', {"input_tokens": 10, "output_tokens": 5})
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, return_value=mock_response):
            passed, reason, usage = await _validate_step_output(
                {"name": "Test", "inputs": [{"name": "Input", "value": "test"}]},
                "Some output",
                {},
            )
        assert passed is True
        assert reason == "Looks good"

    @pytest.mark.asyncio
    async def test_validation_fails(self):
        mock_response = ('{"passed": false, "reason": "Output is empty"}', {"input_tokens": 10, "output_tokens": 5})
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, return_value=mock_response):
            passed, reason, usage = await _validate_step_output(
                {"name": "Test", "inputs": [{"name": "Input", "value": "test"}]},
                "",
                {},
            )
        assert passed is False
        assert "empty" in reason.lower()

    @pytest.mark.asyncio
    async def test_validation_unparseable_response_passes(self):
        mock_response = ("I cannot parse this properly", {"input_tokens": 5, "output_tokens": 5})
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, return_value=mock_response):
            passed, reason, _ = await _validate_step_output({"name": "T", "inputs": []}, "out", {})
        assert passed is True

    @pytest.mark.asyncio
    async def test_validation_exception_passes(self):
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, side_effect=Exception("API error")):
            passed, reason, usage = await _validate_step_output({"name": "T", "inputs": []}, "out", {})
        assert passed is True
        assert "Validation error" in reason
        assert usage == {}

    @pytest.mark.asyncio
    async def test_validation_model_selection(self):
        """Step override > pipeline default > haiku fallback."""
        mock_response = ('{"passed": true, "reason": "ok"}', {"input_tokens": 1, "output_tokens": 1})
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, return_value=mock_response) as mock_call:
            # With step override
            await _validate_step_output(
                {"name": "T", "inputs": [], "validation_model": "custom-model"},
                "out",
                {"validation_model": "pipeline-model"},
            )
            call_args = mock_call.call_args
            assert call_args[0][1] == "custom-model"

    @pytest.mark.asyncio
    async def test_validation_no_inputs(self):
        """When no inputs provided, should still work with placeholder text."""
        mock_response = ('{"passed": true, "reason": "ok"}', {})
        with patch("services.pipeline_engine.chat_complete", new_callable=AsyncMock, return_value=mock_response) as mock_call:
            passed, _, _ = await _validate_step_output({"name": "T", "inputs": []}, "out", {})
            assert passed is True
            # User message should contain "No explicit inputs"
            user_msg = mock_call.call_args[0][0][0]["content"]
            assert "No explicit inputs" in user_msg


# ── _prep_step ───────────────────────────────────────────────────────


class TestPrepStep:

    def test_basic_template_resolution(self):
        pipeline_run = {
            "steps": [
                {
                    "id": "prev",
                    "name": "Previous",
                    "outputs": [{"name": "Previous", "value": "world"}],
                    "tool_outputs": [],
                },
            ],
            "inputs": [{"name": "Start", "value": "initial"}],
            "outputs": [],
        }
        step = {
            "id": "current",
            "inputs": [{"name": "Input", "value": "Hello {{ Previous }}", "is_default": True}],
        }
        tool = {
            "request_inputs": [{"name": "Input", "value": "{{ Input }}", "is_default": True}],
        }

        action_params, main_input, other_inputs, output_props = _prep_step(pipeline_run, step, tool)

        assert main_input["value"] == "Hello world"

    def test_main_input_fallback_to_previous_output(self):
        """When step's Input is empty, it's populated from the previous step's output.
        The tool's request_inputs then resolves {{ Input }} from the step_inputs."""
        pipeline_run = {
            "steps": [
                {
                    "id": "prev",
                    "name": "Prev",
                    "outputs": [{"name": "Prev", "value": "from_prev"}],
                    "tool_outputs": [],
                },
            ],
            "inputs": [{"name": "Start", "value": "initial"}],
            "outputs": [],
        }
        step = {
            "id": "current",
            "inputs": [{"name": "Input", "value": "", "is_default": True}],
        }
        tool = {
            "request_inputs": [{"name": "Input", "value": "{{ Input }}", "is_default": True}],
        }

        _, main_input, _, _ = _prep_step(pipeline_run, step, tool)
        # Step Input gets populated from prev output, then tool resolves {{ Input }}
        assert main_input["value"] == "from_prev"

    def test_main_input_fallback_to_pipeline_input(self):
        """When no previous steps, step's Input falls back to pipeline inputs."""
        pipeline_run = {
            "steps": [],
            "inputs": [{"name": "Start", "value": "pipeline_val"}],
            "outputs": [],
        }
        step = {
            "id": "current",
            "inputs": [{"name": "Input", "value": "", "is_default": True}],
        }
        tool = {
            "request_inputs": [{"name": "Input", "value": "{{ Input }}", "is_default": True}],
        }

        _, main_input, _, _ = _prep_step(pipeline_run, step, tool)
        assert main_input["value"] == "pipeline_val"

    def test_resolved_inputs_stored(self):
        pipeline_run = {"steps": [], "inputs": [], "outputs": []}
        step = {
            "id": "s1",
            "inputs": [{"name": "Prompt", "value": "Hello"}],
        }
        tool = {"request_inputs": []}

        _prep_step(pipeline_run, step, tool)
        assert step["resolved_inputs"] == [{"name": "Prompt", "value": "Hello"}]

    def test_tool_outputs_as_action_params(self):
        pipeline_run = {
            "steps": [
                {
                    "id": "prev",
                    "name": "AgentStep",
                    "outputs": [],
                    "tool_outputs": ["Called tool X", "Got result Y"],
                },
            ],
            "inputs": [],
            "outputs": [],
        }
        step = {
            "id": "current",
            "inputs": [{"name": "Input", "value": "{{ AgentStepActions }}", "is_default": True}],
        }
        tool = {
            "request_inputs": [{"name": "Input", "value": "{{ Input }}", "is_default": True}],
        }

        action_params, main_input, _, _ = _prep_step(pipeline_run, step, tool)
        assert len(action_params) == 1
        assert "AgentStepActions" in action_params[0]["name"]
        assert "Called tool X" in main_input["value"]


# ── _clear_loop_visited ──────────────────────────────────────────────


class TestClearLoopVisited:

    def test_basic_clear(self):
        steps_by_id = {
            "s1": {"id": "s1", "status": PipelineStatusType.Completed,
                   "next_steps": ["s2"], "next_steps_true": [], "next_steps_false": []},
            "s2": {"id": "s2", "status": PipelineStatusType.Completed,
                   "next_steps": ["s3"], "next_steps_true": [], "next_steps_false": []},
            "s3": {"id": "s3", "status": PipelineStatusType.Completed,
                   "next_steps": [], "next_steps_true": [], "next_steps_false": []},
            "loop": {"id": "loop", "status": PipelineStatusType.Completed,
                     "next_steps": ["s1"], "next_steps_true": [], "next_steps_false": []},
        }
        visited = {"s1", "s2", "s3", "loop"}

        _clear_loop_visited(steps_by_id, visited, ["s1"], "loop")

        # s1, s2, s3 should be removed from visited and reset to Pending
        assert "s1" not in visited
        assert "s2" not in visited
        assert "s3" not in visited
        assert "loop" in visited  # loop_step_id should NOT be cleared
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Pending
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Pending

    def test_stops_at_loop_step_id(self):
        steps_by_id = {
            "a": {"id": "a", "status": PipelineStatusType.Completed,
                  "next_steps": ["loop"], "next_steps_true": [], "next_steps_false": []},
            "loop": {"id": "loop", "status": PipelineStatusType.Completed,
                     "next_steps": ["a"], "next_steps_true": [], "next_steps_false": []},
        }
        visited = {"a", "loop"}

        _clear_loop_visited(steps_by_id, visited, ["a"], "loop")

        assert "a" not in visited
        assert "loop" in visited
