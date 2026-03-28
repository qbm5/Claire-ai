"""Tests for pipeline step execution handlers (_execute_step)."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from models.enums import ToolType, PipelineStatusType, EndpointMethod
from services.pipeline_engine import _execute_step, stop_commands


def _make_pipeline_run(steps=None, inputs=None):
    return {
        "id": "run-1",
        "pipeline_id": "p-1",
        "pipeline_snapshot": {"edges": []},
        "steps": steps or [],
        "inputs": inputs or [],
        "outputs": [],
        "status": PipelineStatusType.Running,
        "memories": [],
    }


def _make_step(step_id="s1", name="Step 1", tool_type=ToolType.LLM, **kwargs):
    step = {
        "id": step_id,
        "name": name,
        "inputs": kwargs.pop("inputs", [{"name": "Input", "value": "test input", "is_default": True}]),
        "outputs": [],
        "status": PipelineStatusType.Running,
        "call_cost": [],
        "tool_outputs": [],
        "pre_process": kwargs.pop("pre_process", ""),
        "post_process": kwargs.pop("post_process", ""),
        "tool": {"type": tool_type, **kwargs.pop("tool_extra", {})},
    }
    step.update(kwargs)
    return step


def _make_tool(tool_type=ToolType.LLM, **kwargs):
    tool = {
        "type": tool_type,
        "prompt": kwargs.pop("prompt", "{{ Input }}"),
        "system_prompt": kwargs.pop("system_prompt", "You are helpful."),
        "model": kwargs.pop("model", "test-model"),
        "request_inputs": kwargs.pop("request_inputs", [
            {"name": "Input", "value": "{{ Input }}", "is_default": True},
        ]),
        "response_structure": kwargs.pop("response_structure", []),
    }
    tool.update(kwargs)
    return tool


# ── LLM Step ────────────────────────────────────────────────────────


class TestLLMStep:

    @pytest.mark.asyncio
    async def test_basic_streaming(self):
        """LLM step streams text chunks and accumulates output."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "Hello "}
            yield {"type": "text", "text": "world"}
            yield {"type": "usage", "model": "test", "input_tokens": 10, "output_tokens": 5}

        pl_run = _make_pipeline_run()
        step = _make_step()
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, agent_text, iter_outputs = await _execute_step(pl_run, step, tool, sem)

        assert output == "Hello world"
        assert agent_text is None
        assert len(step["call_cost"]) == 1
        assert step["call_cost"][0]["input_token_count"] == 10

    @pytest.mark.asyncio
    async def test_structured_output(self):
        """LLM step with response_structure uses forced tool_use."""
        mock_result = {
            "content": [
                {"type": "tool_use", "name": "structured_output", "input": {"key": "value"}},
            ],
            "usage": {"model": "test", "input_tokens": 15, "output_tokens": 8},
        }

        pl_run = _make_pipeline_run()
        step = _make_step()
        tool = _make_tool(response_structure=[{"key": "key", "type": "string"}])
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_with_tools", new_callable=AsyncMock, return_value=mock_result), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert json.loads(output) == {"key": "value"}

    @pytest.mark.asyncio
    async def test_stop_command_interrupts(self):
        """Stop command halts LLM streaming mid-stream."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "partial"}
            stop_commands.add("run-1")
            yield {"type": "text", "text": " should not appear"}

        pl_run = _make_pipeline_run()
        step = _make_step()
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        try:
            with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
                 patch("services.pipeline_engine.broadcast"), \
                 patch("services.pipeline_engine.run_log"), \
                 patch("services.artifact_service.init_artifact_context"):
                output, _, _ = await _execute_step(pl_run, step, tool, sem)

            assert output == "partial"
        finally:
            stop_commands.discard("run-1")

    @pytest.mark.asyncio
    async def test_pre_process_js_splits_input(self):
        """Pre-process JS can split input into multiple iterations."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "processed"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        pl_run = _make_pipeline_run()
        step = _make_step(pre_process='function process(x) { return ["a", "b"]; }')
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, iter_outputs = await _execute_step(pl_run, step, tool, sem)

        # Should process twice (once per split item)
        assert output == "processedprocessed"
        assert len(iter_outputs) == 2

    @pytest.mark.asyncio
    async def test_post_process_js_transforms_output(self):
        """Post-process JS transforms the final output."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "hello"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        pl_run = _make_pipeline_run()
        step = _make_step(post_process='function process(x) { return x.toUpperCase(); }')
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "HELLO"


# ── Endpoint Step ───────────────────────────────────────────────────


class TestEndpointStep:

    @pytest.mark.asyncio
    async def test_get_request(self):
        """Endpoint step makes GET request and returns response text."""
        mock_response = MagicMock()
        mock_response.text = '{"result": "ok"}'
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Endpoint)
        tool = _make_tool(
            tool_type=ToolType.Endpoint,
            endpoint_url="https://api.example.com/data",
            endpoint_method=EndpointMethod.GET,
            endpoint_query=[],
            endpoint_headers="",
            endpoint_body="",
            endpoint_timeout=30,
        )
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.httpx.AsyncClient", return_value=mock_client), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == '{"result": "ok"}'
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_request_with_body(self):
        """Endpoint step makes POST request with JSON body."""
        mock_response = MagicMock()
        mock_response.text = "created"
        mock_response.status_code = 201

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Endpoint)
        tool = _make_tool(
            tool_type=ToolType.Endpoint,
            endpoint_url="https://api.example.com/data",
            endpoint_method=EndpointMethod.POST,
            endpoint_query=[],
            endpoint_headers=[{"key": "Authorization", "value": "Bearer token"}],
            endpoint_body=[{"key": "name", "value": "test"}],
            endpoint_timeout=30,
        )
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.httpx.AsyncClient", return_value=mock_client), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "created"
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"] == {"name": "test"}
        assert call_kwargs.kwargs["headers"] == {"Authorization": "Bearer token"}


# ── Agent Step ──────────────────────────────────────────────────────


class TestAgentStep:

    @pytest.mark.asyncio
    async def test_agent_text_only(self):
        """Agent step with no tool calls returns text as output."""
        async def mock_agent_loop(*args, **kwargs):
            yield {"type": "text", "text": "Agent says hello"}
            yield {"type": "usage", "model": "test", "input_tokens": 20, "output_tokens": 10}

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Agent)
        tool = _make_tool(tool_type=ToolType.Agent, name="TestAgent", id="t1")
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.run_agent_loop", side_effect=mock_agent_loop), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, agent_text, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "Agent says hello"
        assert agent_text is None  # No tool calls, so no separate agent text

    @pytest.mark.asyncio
    async def test_agent_with_tool_calls(self):
        """Agent step with tool calls uses last tool result as chaining output."""
        async def mock_agent_loop(*args, **kwargs):
            yield {"type": "text", "text": "Let me check..."}
            yield {"type": "tool_call", "name": "search", "input": {"query": "test"}}
            yield {"type": "tool_result", "name": "search", "result": "Found: important data"}
            yield {"type": "text", "text": "Based on my search, here's the answer."}
            yield {"type": "usage", "model": "test", "input_tokens": 30, "output_tokens": 20}

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Agent)
        tool = _make_tool(tool_type=ToolType.Agent, name="TestAgent", id="t1")
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.run_agent_loop", side_effect=mock_agent_loop), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, agent_text, _ = await _execute_step(pl_run, step, tool, sem)

        # Chaining output should be the last tool result
        assert output == "Found: important data"
        # Agent text is the chatty summary
        assert "Let me check" in agent_text
        # Tool outputs tracked
        assert len(step["tool_outputs"]) == 2  # tool_call + tool_result

    @pytest.mark.asyncio
    async def test_agent_with_artifacts(self):
        """Agent step collects artifacts."""
        async def mock_agent_loop(*args, **kwargs):
            yield {"type": "text", "text": "Created file"}
            yield {"type": "artifacts", "artifacts": [{"name": "output.png", "url": "/artifacts/run-1/output.png"}]}
            yield {"type": "usage", "model": "test", "input_tokens": 5, "output_tokens": 5}

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Agent)
        tool = _make_tool(tool_type=ToolType.Agent, name="TestAgent", id="t1")
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.run_agent_loop", side_effect=mock_agent_loop), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            await _execute_step(pl_run, step, tool, sem)

        assert len(step["artifacts"]) == 1
        assert step["artifacts"][0]["name"] == "output.png"


# ── If Step ─────────────────────────────────────────────────────────


class TestIfStep:

    @pytest.mark.asyncio
    async def test_condition_true(self):
        """If step returns 'true' when condition evaluates to True."""
        mock_eval = AsyncMock(return_value=(True, "Condition met", {"model": "test", "input_tokens": 5, "output_tokens": 3}))

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.If)
        tool = _make_tool(tool_type=ToolType.If)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.evaluate_condition", mock_eval), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "true"
        assert step["status_text"] == "Condition met"
        assert len(step["call_cost"]) == 1

    @pytest.mark.asyncio
    async def test_condition_false(self):
        """If step returns 'false' when condition evaluates to False."""
        mock_eval = AsyncMock(return_value=(False, "Condition not met", {"model": "test", "input_tokens": 5, "output_tokens": 3}))

        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.If)
        tool = _make_tool(tool_type=ToolType.If)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.evaluate_condition", mock_eval), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "false"


# ── LoopCounter Step ────────────────────────────────────────────────


class TestLoopCounterStep:

    @pytest.mark.asyncio
    async def test_increment_within_limit(self):
        """LoopCounter passes through input and increments count."""
        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.LoopCounter)
        tool = _make_tool(tool_type=ToolType.LoopCounter, max_passes=5)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "test input"
        assert step["_loop_count"] == 1
        assert step["_loop_halted"] is False
        assert "Pass 1 of 5" in step["status_text"]

    @pytest.mark.asyncio
    async def test_halts_at_max_passes(self):
        """LoopCounter halts when count exceeds max_passes."""
        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.LoopCounter, _loop_count=4)
        tool = _make_tool(tool_type=ToolType.LoopCounter, max_passes=5)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert step["_loop_count"] == 5
        assert step["_loop_halted"] is False  # exactly at 5, not over

        # Now do one more pass - should halt
        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert step["_loop_count"] == 6
        assert step["_loop_halted"] is True
        assert output == ""


# ── Start Step ──────────────────────────────────────────────────────


class TestStartStep:

    @pytest.mark.asyncio
    async def test_start_passes_pipeline_inputs(self):
        """Start step passes through pipeline inputs as output."""
        pl_run = _make_pipeline_run(inputs=[
            {"name": "Query", "value": "hello"},
            {"name": "Mode", "value": "fast"},
        ])
        step = _make_step(tool_type=ToolType.Start)
        tool = _make_tool(tool_type=ToolType.Start)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert "hello" in output
        assert "fast" in output
        assert "_start_outputs" in step
        assert len(step["_start_outputs"]) == 2

    @pytest.mark.asyncio
    async def test_start_no_inputs(self):
        """Start step with no pipeline inputs passes through step input."""
        pl_run = _make_pipeline_run(inputs=[])
        step = _make_step(tool_type=ToolType.Start)
        tool = _make_tool(tool_type=ToolType.Start)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "test input"


# ── Wait Step ───────────────────────────────────────────────────────


class TestWaitStep:

    @pytest.mark.asyncio
    async def test_wait_passes_through(self):
        """Wait step passes through input and sets status text."""
        pl_run = _make_pipeline_run(steps=[
            {"id": "s_branch1", "next_steps": ["s1"], "next_steps_true": [], "next_steps_false": []},
            {"id": "s_branch2", "next_steps": ["s1"], "next_steps_true": [], "next_steps_false": []},
        ])
        step = _make_step(step_id="s1", tool_type=ToolType.Wait)
        tool = _make_tool(tool_type=ToolType.Wait)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "test input"
        assert "2 branches" in step["status_text"]


# ── Pause/End Step ──────────────────────────────────────────────────


class TestPauseEndStep:

    @pytest.mark.asyncio
    async def test_pause_passes_through(self):
        """Pause step passes through input."""
        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.Pause)
        tool = _make_tool(tool_type=ToolType.Pause)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "test input"

    @pytest.mark.asyncio
    async def test_end_passes_through(self):
        """End step passes through input."""
        pl_run = _make_pipeline_run()
        step = _make_step(tool_type=ToolType.End)
        tool = _make_tool(tool_type=ToolType.End)
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            output, _, _ = await _execute_step(pl_run, step, tool, sem)

        assert output == "test input"


# ── Memory integration in steps ─────────────────────────────────────


class TestStepMemoryIntegration:

    @pytest.mark.asyncio
    async def test_llm_step_injects_memory_messages(self):
        """LLM step includes memory messages before user message."""
        captured_messages = []

        async def mock_stream(messages, model, system_prompt):
            captured_messages.extend(messages)
            yield {"type": "text", "text": "response"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        pl_run = _make_pipeline_run()
        pl_run["pipeline_snapshot"] = {
            "edges": [
                {"source": "s1", "source_handle": "right_memory", "target": "mem1"},
            ],
        }
        pl_run["memories"] = [
            {"id": "mem1", "messages": [
                {"role": "user", "content": "old question", "timestamp": "2024-01-01T00:00:00"},
                {"role": "assistant", "content": "old answer", "timestamp": "2024-01-01T00:00:01"},
            ]},
        ]
        step = _make_step()
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            await _execute_step(pl_run, step, tool, sem)

        # Memory messages should appear before user message
        assert len(captured_messages) == 3
        assert captured_messages[0]["content"] == "old question"
        assert captured_messages[1]["content"] == "old answer"

    @pytest.mark.asyncio
    async def test_memory_appended_after_step(self):
        """After step execution, memory is updated with the exchange."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "new answer"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        pl_run = _make_pipeline_run()
        pl_run["pipeline_snapshot"] = {
            "edges": [
                {"source": "s1", "source_handle": "right_memory", "target": "mem1"},
            ],
        }
        pl_run["memories"] = [{"id": "mem1", "messages": []}]
        step = _make_step()
        tool = _make_tool()
        sem = asyncio.Semaphore(5)

        with patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.broadcast"), \
             patch("services.pipeline_engine.run_log"), \
             patch("services.artifact_service.init_artifact_context"):
            await _execute_step(pl_run, step, tool, sem)

        # Memory should now have the exchange
        mem = pl_run["memories"][0]
        assert len(mem["messages"]) == 2
        assert mem["messages"][1]["content"] == "new answer"
