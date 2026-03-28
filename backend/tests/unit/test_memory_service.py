"""Tests for memory_service."""

import json
import os
import pytest

from services.memory_service import load_memory, save_memory, append_message, clear_memory


@pytest.fixture()
def memory_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("services.memory_service.MEMORY_DIR", str(tmp_path))
    return tmp_path


class TestLoadMemory:

    def test_load_existing(self, memory_dir):
        path = memory_dir / "hist-1.json"
        messages = [{"role": "user", "content": "hi"}]
        path.write_text(json.dumps(messages))
        result = load_memory("hist-1")
        assert result == messages

    def test_load_nonexistent_returns_empty(self, memory_dir):
        assert load_memory("nonexistent") == []

    def test_load_invalid_json_raises(self, memory_dir):
        path = memory_dir / "bad.json"
        path.write_text("not json")
        with pytest.raises(Exception):
            load_memory("bad")


class TestSaveMemory:

    def test_save_creates_file(self, memory_dir):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        save_memory("hist-2", messages)
        path = memory_dir / "hist-2.json"
        assert path.exists()
        assert json.loads(path.read_text()) == messages

    def test_save_overwrites(self, memory_dir):
        save_memory("hist-3", [{"role": "user", "content": "old"}])
        save_memory("hist-3", [{"role": "user", "content": "new"}])
        path = memory_dir / "hist-3.json"
        assert json.loads(path.read_text()) == [{"role": "user", "content": "new"}]


class TestAppendMessage:

    def test_append_to_existing(self, memory_dir):
        save_memory("hist-4", [{"role": "user", "content": "first"}])
        append_message("hist-4", "assistant", "response")
        result = load_memory("hist-4")
        assert len(result) == 2
        assert result[1]["content"] == "response"

    def test_append_to_new(self, memory_dir):
        append_message("new-hist", "user", "hello")
        result = load_memory("new-hist")
        assert len(result) == 1


class TestClearMemory:

    def test_clear_existing(self, memory_dir):
        save_memory("hist-5", [{"role": "user", "content": "x"}])
        clear_memory("hist-5")
        assert not (memory_dir / "hist-5.json").exists()

    def test_clear_nonexistent_no_error(self, memory_dir):
        clear_memory("nonexistent")  # Should not raise
