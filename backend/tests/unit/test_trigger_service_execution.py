"""Tests for trigger_service execution logic."""

import asyncio
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from services.trigger_service import (
    fire_trigger,
    _entry_key,
    cancel_trigger,
    _scheduler_tasks,
    _watcher_observers,
)


class TestEntryKey:

    def test_uses_id_first(self):
        entry = SimpleNamespace(id="rss-123", link="https://example.com", title="Test")
        assert _entry_key(entry) == "rss-123"

    def test_falls_back_to_link(self):
        entry = SimpleNamespace(id="", link="https://example.com/article", title="Test")
        assert _entry_key(entry) == "https://example.com/article"

    def test_falls_back_to_md5_title(self):
        entry = SimpleNamespace(id="", link="", title="My Article Title")
        expected = hashlib.md5("My Article Title".encode()).hexdigest()
        assert _entry_key(entry) == expected

    def test_no_id_attr(self):
        entry = SimpleNamespace(link="http://example.com", title="T")
        assert _entry_key(entry) == "http://example.com"


class TestFireTrigger:

    @pytest.mark.asyncio
    async def test_trigger_not_found(self):
        with patch("services.trigger_service.get_by_id", return_value=None):
            result = await fire_trigger("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_cron_trigger_fires_code(self):
        trigger = {
            "id": "t1", "name": "Test Cron", "trigger_type": "Cron",
            "code": "def on_trigger(ctx): return {'message': 'ok'}",
            "connections": [], "fire_count": 0,
        }
        mock_fn = MagicMock(return_value={"message": "ok"})

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d), \
             patch("services.trigger_service.load_trigger_function", return_value=mock_fn):
            result = await fire_trigger("t1")

        assert result["status"] == "fired"
        mock_fn.assert_called_once()
        assert result["outputs"]["message"] == "ok"

    @pytest.mark.asyncio
    async def test_skip_code_uses_event_context_directly(self):
        trigger = {
            "id": "t1", "name": "Test", "trigger_type": "Webhook",
            "code": "", "connections": [], "fire_count": 0,
        }

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d):
            result = await fire_trigger("t1", {"data": "webhook_payload"}, skip_code=True)

        assert result["status"] == "fired"
        # outputs is a dict merged from context + event_context
        assert result["outputs"]["data"] == "webhook_payload"

    @pytest.mark.asyncio
    async def test_code_error_returns_error_result(self):
        trigger = {
            "id": "t1", "name": "Bad", "trigger_type": "Cron",
            "code": "def on_trigger(ctx): raise ValueError('boom')",
            "connections": [], "fire_count": 0,
        }
        def bad_fn(ctx):
            raise ValueError("boom")

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d), \
             patch("services.trigger_service.load_trigger_function", return_value=bad_fn):
            result = await fire_trigger("t1")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_async_code_function_awaited(self):
        trigger = {
            "id": "t1", "name": "Async", "trigger_type": "Cron",
            "code": "async def on_trigger(ctx): return {'async': True}",
            "connections": [], "fire_count": 0,
        }

        async def async_fn(ctx):
            return {"async_result": True}

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d), \
             patch("services.trigger_service.load_trigger_function", return_value=async_fn):
            result = await fire_trigger("t1")

        assert result["status"] == "fired"
        assert result["outputs"]["async_result"] is True

    @pytest.mark.asyncio
    async def test_connected_pipelines_fired(self):
        trigger = {
            "id": "t1", "name": "Connected", "trigger_type": "Cron",
            "code": "def on_trigger(ctx): return {'message': 'hello'}",
            "connections": [
                {"pipeline_id": "p1", "is_enabled": True,
                 "input_mappings": [{"pipeline_input": "Start", "expression": "{{ message }}"}]},
            ],
            "fire_count": 0,
        }
        pipeline = {"id": "p1", "name": "Test Pipeline", "steps": [], "inputs": []}
        mock_fn = MagicMock(return_value={"message": "hello"})

        def mock_get_by_id(table, id):
            if table == "triggers":
                return trigger
            if table == "pipelines":
                return pipeline
            return None

        with patch("services.trigger_service.get_by_id", side_effect=mock_get_by_id), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d), \
             patch("services.trigger_service.load_trigger_function", return_value=mock_fn), \
             patch("services.trigger_service.run_pipeline", new_callable=AsyncMock), \
             patch("asyncio.create_task"):
            result = await fire_trigger("t1")

        assert result["status"] == "fired"
        assert len(result["pipelines"]) == 1
        assert result["pipelines"][0]["pipeline_id"] == "p1"

    @pytest.mark.asyncio
    async def test_disabled_connections_skipped(self):
        trigger = {
            "id": "t1", "name": "Disabled", "trigger_type": "Cron",
            "code": "", "connections": [
                {"pipeline_id": "p1", "is_enabled": False, "input_mappings": []},
            ],
            "fire_count": 0,
        }

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d), \
             patch("services.trigger_service.load_trigger_function", return_value=None):
            result = await fire_trigger("t1")

        assert result["pipelines"] == []

    @pytest.mark.asyncio
    async def test_no_code_and_no_fn(self):
        """Trigger with empty code and no saved function uses context as outputs."""
        trigger = {
            "id": "t1", "name": "NoCode", "trigger_type": "Cron",
            "code": "", "connections": [], "fire_count": 0,
        }

        with patch("services.trigger_service.get_by_id", return_value=trigger), \
             patch("services.trigger_service.upsert", side_effect=lambda t, d: d):
            result = await fire_trigger("t1")

        assert result["status"] == "fired"
        # Outputs should be the context dict (defaults for Cron)
        assert "trigger_type" in result["outputs"]


class TestCancelTrigger:

    def test_cancels_scheduled_task(self):
        mock_task = MagicMock()
        mock_task.done.return_value = False
        _scheduler_tasks["cancel-test"] = mock_task

        cancel_trigger("cancel-test")

        mock_task.cancel.assert_called_once()
        assert "cancel-test" not in _scheduler_tasks

    def test_stops_watcher(self):
        mock_observer = MagicMock()
        _watcher_observers["watcher-test"] = mock_observer

        cancel_trigger("watcher-test")

        mock_observer.stop.assert_called_once()
        assert "watcher-test" not in _watcher_observers

    def test_cancel_nonexistent_no_error(self):
        cancel_trigger("nonexistent")  # Should not raise
