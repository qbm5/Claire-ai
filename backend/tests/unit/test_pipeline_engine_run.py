"""Integration-level unit tests for run_pipeline()."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from models.enums import ToolType, PipelineStatusType
from services.pipeline_engine import run_pipeline, stop_commands, stop_pipeline


def _make_run(run_id, steps, inputs=None, pipeline_snapshot=None):
    """Helper to create a pipeline run dict in the DB."""
    if pipeline_snapshot is None:
        pipeline_snapshot = {"edges": [], "memories": []}
    return {
        "id": run_id,
        "pipeline_id": "p1",
        "pipeline_snapshot": pipeline_snapshot,
        "steps": steps,
        "inputs": inputs or [],
        "outputs": [],
        "status": PipelineStatusType.Running,
        "current_step": 0,
        "created_at": "2024-01-01T00:00:00Z",
    }


def _make_step_def(step_id, name, tool_type=ToolType.LLM, **kwargs):
    """Helper to create a step definition."""
    return {
        "id": step_id,
        "name": name,
        "tool_id": "",
        "tool": {"type": tool_type, "model": "test-model", "prompt": "{{ Input }}",
                 "system_prompt": "", "request_inputs": [
                     {"name": "Input", "value": "{{ Input }}", "is_default": True}],
                 "response_structure": [], **kwargs.pop("tool_extra", {})},
        "inputs": kwargs.pop("inputs", [{"name": "Input", "value": "", "is_default": True}]),
        "outputs": [],
        "status": PipelineStatusType.Pending,
        "status_text": "",
        "call_cost": [],
        "tool_outputs": [],
        "iteration_outputs": None,
        "split_count": 0,
        "next_steps": kwargs.pop("next_steps", []),
        "next_steps_true": kwargs.pop("next_steps_true", []),
        "next_steps_false": kwargs.pop("next_steps_false", []),
        "is_start": kwargs.pop("is_start", False),
        "disabled": kwargs.pop("disabled", False),
        "pre_process": "",
        "post_process": "",
        **kwargs,
    }


# Common mocks context manager
def _patch_pipeline_deps(db_data):
    """Create patches for pipeline execution dependencies."""
    def mock_get_by_id(table, id):
        if table == "pipeline_runs":
            return db_data.get(id)
        return None

    def mock_upsert(table, data):
        if table == "pipeline_runs":
            db_data[data["id"]] = data
        return data

    return (
        patch("services.pipeline_engine.get_by_id", side_effect=mock_get_by_id),
        patch("services.pipeline_engine.upsert", side_effect=mock_upsert),
        patch("services.pipeline_engine.get_all", return_value=[]),
        patch("services.pipeline_engine.broadcast"),
        patch("services.pipeline_engine.run_log"),
        patch("services.pipeline_engine.flush_to_run"),
        patch("services.artifact_service.init_artifact_context"),
    )


class TestRunPipelineSingleStep:

    @pytest.mark.asyncio
    async def test_single_llm_step_completes(self):
        """Pipeline with a single LLM step executes and completes."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "Result"}
            yield {"type": "usage", "model": "test", "input_tokens": 5, "output_tokens": 3}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "hello"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Completed
        assert db["r1"]["steps"][0]["status"] == PipelineStatusType.Completed
        assert db["r1"]["steps"][0]["outputs"][0]["value"] == "Result"

    @pytest.mark.asyncio
    async def test_nonexistent_run_returns_early(self):
        """run_pipeline returns early if run_id not found."""
        with patch("services.pipeline_engine.get_by_id", return_value=None):
            await run_pipeline("nonexistent")
            # Should not raise


class TestRunPipelineMultiStep:

    @pytest.mark.asyncio
    async def test_linear_chain(self):
        """Multi-step linear pipeline chains outputs forward."""
        call_count = 0

        async def mock_stream(messages, model, system_prompt):
            nonlocal call_count
            call_count += 1
            yield {"type": "text", "text": f"output_{call_count}"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, next_steps=["s2"]),
            _make_step_def("s2", "Step 2", next_steps=["s3"]),
            _make_step_def("s3", "Step 3"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "start"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Completed
        assert call_count == 3
        # All steps completed
        for step in db["r1"]["steps"]:
            assert step["status"] == PipelineStatusType.Completed


class TestRunPipelineBranching:

    @pytest.mark.asyncio
    async def test_if_true_branch(self):
        """If step routes to true branch when condition is true."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "branch output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        mock_eval = AsyncMock(return_value=(True, "Condition met", {"model": "t", "input_tokens": 1, "output_tokens": 1}))

        steps = [
            _make_step_def("s1", "Start", tool_type=ToolType.Start, is_start=True, next_steps=["s_if"]),
            _make_step_def("s_if", "Condition", tool_type=ToolType.If,
                          next_steps_true=["s_true"], next_steps_false=["s_false"]),
            _make_step_def("s_true", "True Branch"),
            _make_step_def("s_false", "False Branch"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "test"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine.evaluate_condition", mock_eval):
            await run_pipeline("r1")

        steps_by_id = {s["id"]: s for s in db["r1"]["steps"]}
        assert steps_by_id["s_true"]["status"] == PipelineStatusType.Completed
        assert steps_by_id["s_false"]["status"] == PipelineStatusType.Pending  # Not executed


class TestRunPipelineStop:

    @pytest.mark.asyncio
    async def test_stop_command_halts_pipeline(self):
        """Stop command prevents further step execution."""
        call_count = 0

        async def mock_stream(messages, model, system_prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                stop_commands.add("r1")
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, next_steps=["s2"]),
            _make_step_def("s2", "Step 2"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        try:
            patches = _patch_pipeline_deps(db)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
                 patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
                await run_pipeline("r1")
        finally:
            stop_commands.discard("r1")

        assert db["r1"]["status"] == PipelineStatusType.Failed
        steps_by_id = {s["id"]: s for s in db["r1"]["steps"]}
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Failed


class TestRunPipelineDisabled:

    @pytest.mark.asyncio
    async def test_disabled_step_skipped(self):
        """Disabled steps are skipped, next steps still queued."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Start", is_start=True, next_steps=["s2"]),
            _make_step_def("s2", "Disabled", disabled=True, next_steps=["s3"]),
            _make_step_def("s3", "End"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Completed
        steps_by_id = {s["id"]: s for s in db["r1"]["steps"]}
        assert steps_by_id["s3"]["status"] == PipelineStatusType.Completed


class TestRunPipelineRerun:

    @pytest.mark.asyncio
    async def test_completed_steps_skipped_on_rerun(self):
        """Already-completed steps from rerun are skipped, only pending steps execute."""
        call_count = 0

        async def mock_stream(messages, model, system_prompt):
            nonlocal call_count
            call_count += 1
            yield {"type": "text", "text": f"new_output_{call_count}"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, next_steps=["s2"]),
            _make_step_def("s2", "Step 2"),
        ]
        # s1 already completed (from rerun)
        steps[0]["status"] = PipelineStatusType.Completed
        steps[0]["outputs"] = [{"name": "Step 1", "value": "old_output"}]

        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert call_count == 1  # Only s2 executed
        steps_by_id = {s["id"]: s for s in db["r1"]["steps"]}
        assert steps_by_id["s1"]["outputs"][0]["value"] == "old_output"  # Preserved
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Completed


class TestRunPipelineStepRetry:

    @pytest.mark.asyncio
    async def test_step_retries_on_failure(self):
        """Step retries on exception up to max_retries."""
        attempt = 0

        async def mock_stream(messages, model, system_prompt):
            nonlocal attempt
            attempt += 1
            if attempt <= 1:
                raise Exception("Temporary error")
            yield {"type": "text", "text": "success"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, retry_enabled=True, max_retries=2),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Completed
        assert attempt == 2

    @pytest.mark.asyncio
    async def test_step_fails_after_max_retries(self):
        """Step fails pipeline after exhausting retries."""
        async def mock_stream(messages, model, system_prompt):
            raise Exception("Persistent error")

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, retry_enabled=True, max_retries=1),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Failed


class TestRunPipelinePause:

    @pytest.mark.asyncio
    async def test_pause_after_step(self):
        """Pipeline pauses after step with pause_after=True."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, next_steps=["s2"], pause_after=True),
            _make_step_def("s2", "Step 2"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Paused
        steps_by_id = {s["id"]: s for s in db["r1"]["steps"]}
        assert steps_by_id["s1"]["status"] == PipelineStatusType.Completed
        assert steps_by_id["s2"]["status"] == PipelineStatusType.Pending  # Not yet executed


class TestRunPipelineValidation:

    @pytest.mark.asyncio
    async def test_validation_failure_stops_pipeline(self):
        """Validation failure marks step and pipeline as failed."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "bad output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        mock_validate = AsyncMock(return_value=(False, "Output doesn't match", {"input_tokens": 5, "output_tokens": 3}))

        steps = [
            _make_step_def("s1", "Step 1", is_start=True, validation_enabled=True),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream), \
             patch("services.pipeline_engine._validate_step_output", mock_validate):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Failed
        assert "Validation failed" in db["r1"]["steps"][0]["status_text"]


class TestRunPipelineNoStartFlag:

    @pytest.mark.asyncio
    async def test_first_step_used_as_start(self):
        """When no step has is_start=True, the first step is used."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "output"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "Step 1"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        assert db["r1"]["status"] == PipelineStatusType.Completed


class TestRunPipelineOutputs:

    @pytest.mark.asyncio
    async def test_final_outputs_collected(self):
        """Pipeline collects all step outputs as final outputs."""
        call_count = 0

        async def mock_stream(messages, model, system_prompt):
            nonlocal call_count
            call_count += 1
            yield {"type": "text", "text": f"out{call_count}"}
            yield {"type": "usage", "model": "test", "input_tokens": 1, "output_tokens": 1}

        steps = [
            _make_step_def("s1", "A", is_start=True, next_steps=["s2"]),
            _make_step_def("s2", "B"),
        ]
        run = _make_run("r1", steps, inputs=[{"name": "Input", "value": "x"}])
        db = {"r1": run}

        patches = _patch_pipeline_deps(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch("services.pipeline_engine.chat_stream", side_effect=mock_stream):
            await run_pipeline("r1")

        outputs = db["r1"]["outputs"]
        assert len(outputs) == 2
        values = [o["value"] for o in outputs]
        assert "out1" in values
        assert "out2" in values
