"""Tests for pipeline_logger."""

import pytest
from unittest.mock import patch

from services.pipeline_logger import run_log, get_log_entries, flush_to_run, clear_log, _run_logs


@pytest.fixture(autouse=True)
def clean_logs():
    """Clean up log state between tests."""
    yield
    _run_logs.clear()


class TestRunLog:

    def test_broadcasts_and_stores(self):
        with patch("services.pipeline_logger.broadcast") as mock_broadcast:
            run_log("run-1", "llm", "Called LLM", step_id="s1")

        mock_broadcast.assert_called_once()
        entries = get_log_entries("run-1")
        assert len(entries) == 1
        assert entries[0]["source"] == "llm"
        assert entries[0]["message"] == "Called LLM"
        assert entries[0]["step_id"] == "s1"

    def test_includes_detail(self):
        with patch("services.pipeline_logger.broadcast"):
            run_log("run-1", "test", "msg", detail={"key": "value"})

        entries = get_log_entries("run-1")
        assert entries[0]["detail"] == {"key": "value"}

    def test_trims_at_max_entries(self):
        with patch("services.pipeline_logger.broadcast"):
            for i in range(510):
                run_log("run-trim", "test", f"msg {i}")

        entries = get_log_entries("run-trim")
        assert len(entries) == 500
        assert entries[0]["message"] == "msg 10"  # oldest trimmed


class TestGetLogEntries:

    def test_returns_empty_for_unknown_run(self):
        assert get_log_entries("unknown") == []


class TestFlushToRun:

    def test_writes_entries_to_run_dict(self):
        with patch("services.pipeline_logger.broadcast"):
            run_log("run-flush", "test", "entry 1")
            run_log("run-flush", "test", "entry 2")

        run = {}
        flush_to_run("run-flush", run)
        assert len(run["log_entries"]) == 2

    def test_no_entries_no_key(self):
        run = {}
        flush_to_run("empty-run", run)
        assert "log_entries" not in run


class TestClearLog:

    def test_clears_entries(self):
        with patch("services.pipeline_logger.broadcast"):
            run_log("run-clear", "test", "msg")

        clear_log("run-clear")
        assert get_log_entries("run-clear") == []

    def test_clear_unknown_no_error(self):
        clear_log("unknown")  # Should not raise
