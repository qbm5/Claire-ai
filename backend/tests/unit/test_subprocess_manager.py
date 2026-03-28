"""Tests for subprocess_manager."""

import subprocess
import pytest
from unittest.mock import MagicMock, patch

from services.subprocess_manager import (
    _detect_output_file,
    get_status,
    kill_process,
    _register,
    _unregister,
    _active_processes,
    _lock,
)


class TestDetectOutputFile:

    def test_finds_file_with_extension(self):
        args = ["python", "script.py", "output.csv"]
        assert _detect_output_file(args) == "output.csv"

    def test_finds_last_file_arg(self):
        args = ["ffmpeg", "-i", "input.mp4", "-c", "copy", "output.mp4"]
        assert _detect_output_file(args) == "output.mp4"

    def test_skips_flags(self):
        args = ["python", "-m", "pytest", "--verbose"]
        assert _detect_output_file(args) is None

    def test_skips_stdin_dash(self):
        args = ["python", "-c", "print('hello')", "-"]
        assert _detect_output_file(args) is None

    def test_returns_none_for_no_files(self):
        args = ["echo", "hello"]
        assert _detect_output_file(args) is None

    def test_empty_args(self):
        assert _detect_output_file([]) is None


class TestGetStatus:

    def test_returns_dict(self):
        status = get_status()
        assert "active_count" in status
        assert "processes" in status
        assert isinstance(status["processes"], list)

    def test_reflects_registered_processes(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.args = ["python", "test.py"]
        mock_proc.poll.return_value = None

        with _lock:
            _active_processes[12345] = mock_proc
        try:
            status = get_status()
            assert status["active_count"] >= 1
            pids = [p["pid"] for p in status["processes"]]
            assert 12345 in pids
        finally:
            with _lock:
                _active_processes.pop(12345, None)


class TestKillProcess:

    def test_kills_tracked_process(self):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with _lock:
            _active_processes[99999] = mock_proc
        try:
            with patch("services.subprocess_manager._kill_process_tree") as mock_kill:
                result = kill_process(99999)
            assert result is True
            mock_kill.assert_called_once_with(99999)
        finally:
            with _lock:
                _active_processes.pop(99999, None)

    def test_returns_false_for_unknown(self):
        result = kill_process(88888)
        assert result is False


class TestRegisterUnregister:

    def test_register_and_unregister(self):
        mock_proc = MagicMock()
        mock_proc.pid = 77777
        with patch("services.subprocess_manager._notify_change"):
            _register(mock_proc)
        try:
            assert 77777 in _active_processes
        finally:
            with patch("services.subprocess_manager._notify_change"):
                _unregister(77777)
        assert 77777 not in _active_processes

    def test_unregister_nonexistent_no_error(self):
        with patch("services.subprocess_manager._notify_change"):
            _unregister(66666)  # Should not raise
