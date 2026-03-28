"""Tests for agent_service execution, sandboxing, and function management."""

import asyncio
import inspect
import os
import json
import types
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent_service import (
    _python_type_to_json_type,
    _func_to_tool_schema,
    _parse_param_docs,
    _auto_artifact_result,
    _make_sandboxed_os_module,
    _install_sandboxed_import,
    _sandbox_filesystem,
    save_agent_functions,
    load_agent_functions,
    run_agent_loop,
    _FILE_PATH_RE,
    _ARTIFACT_EXTENSIONS,
)


# ── _parse_param_docs ────────────────────────────────────────────────


class TestParseParamDocs:

    def test_rst_style(self):
        doc = """Do something.

        :param name: The user's name.
        :param age: The user's age.
        """
        result = _parse_param_docs(doc)
        assert result["name"] == "The user's name."
        assert result["age"] == "The user's age."

    def test_google_style(self):
        doc = """Do something.

        Args:
            name: The user's name.
            age: The user's age.
        """
        result = _parse_param_docs(doc)
        assert result["name"] == "The user's name."
        assert result["age"] == "The user's age."

    def test_empty_docstring(self):
        assert _parse_param_docs("") == {}
        assert _parse_param_docs(None) == {}

    def test_no_params(self):
        assert _parse_param_docs("Just a description.") == {}

    def test_mixed_format_uses_rst_first(self):
        doc = """:param x: RST style."""
        result = _parse_param_docs(doc)
        assert result["x"] == "RST style."


# ── _auto_artifact_result ────────────────────────────────────────────


class TestAutoArtifactResult:

    def test_non_string_passthrough(self):
        assert _auto_artifact_result(123) == 123
        assert _auto_artifact_result(None) is None

    def test_no_file_paths(self):
        assert _auto_artifact_result("just text") == "just text"

    def test_file_path_detected_but_not_artifact(self):
        # .txt is not an artifact extension
        with patch("os.path.isfile", return_value=True):
            result = _auto_artifact_result("/tmp/data.txt")
        assert result == "/tmp/data.txt"

    def test_artifact_path_detected_and_saved(self):
        with patch("os.path.isfile", return_value=True), \
             patch("services.agent_service.save_artifact", return_value="/artifacts/run/file.png") as mock_save:
            result = _auto_artifact_result("Output file: /tmp/output.png done")
        mock_save.assert_called_once()
        assert result == "Output file: /tmp/output.png done"

    def test_save_artifact_exception_swallowed(self):
        with patch("os.path.isfile", return_value=True), \
             patch("services.agent_service.save_artifact", side_effect=Exception("fail")):
            result = _auto_artifact_result("/tmp/output.png")
        assert "/tmp/output.png" in result


# ── _make_sandboxed_os_module ────────────────────────────────────────


class TestMakeSandboxedOsModule:

    def test_environ_restricted_to_custom_vars(self):
        sandboxed = _make_sandboxed_os_module({"MY_VAR": "value", "OTHER": "123"})
        assert dict(sandboxed.environ) == {"MY_VAR": "value", "OTHER": "123"}

    def test_getenv_uses_sandboxed_environ(self):
        sandboxed = _make_sandboxed_os_module({"KEY": "val"})
        assert sandboxed.getenv("KEY") == "val"
        assert sandboxed.getenv("PATH") is None
        assert sandboxed.getenv("MISSING", "default") == "default"

    def test_other_os_attrs_preserved(self):
        sandboxed = _make_sandboxed_os_module({})
        assert hasattr(sandboxed, "path")
        assert hasattr(sandboxed, "sep")


# ── _install_sandboxed_import ────────────────────────────────────────


class TestInstallSandboxedImport:

    def test_os_import_returns_sandboxed(self):
        sandboxed_os = _make_sandboxed_os_module({"TEST": "1"})
        module = types.ModuleType("test_mod")
        module.__builtins__ = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
        _install_sandboxed_import(module, sandboxed_os)

        # When the module imports os, it should get the sandboxed version
        exec_globals = {"__builtins__": module.__builtins__}
        exec("import os; result = os.getenv('TEST')", exec_globals)
        assert exec_globals["result"] == "1"

    def test_other_imports_work(self):
        sandboxed_os = _make_sandboxed_os_module({})
        module = types.ModuleType("test_mod")
        module.__builtins__ = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
        _install_sandboxed_import(module, sandboxed_os)

        exec_globals = {"__builtins__": module.__builtins__}
        exec("import json; result = json.dumps({'a': 1})", exec_globals)
        assert exec_globals["result"] == '{"a": 1}'


# ── _sandbox_filesystem ─────────────────────────────────────────────


class TestSandboxFilesystem:

    def test_open_within_workspace_allowed(self, tmp_path):
        workspace = str(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        module = types.ModuleType("test_mod")
        module.__builtins__ = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
        _sandbox_filesystem(module, workspace)

        sandboxed_open = module.__builtins__["open"]
        with sandboxed_open(str(test_file), "r") as f:
            assert f.read() == "content"

    def test_open_outside_workspace_blocked(self, tmp_path):
        workspace = str(tmp_path / "sandbox")
        os.makedirs(workspace, exist_ok=True)

        module = types.ModuleType("test_mod")
        module.__builtins__ = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
        _sandbox_filesystem(module, workspace)

        sandboxed_open = module.__builtins__["open"]
        with pytest.raises(PermissionError):
            sandboxed_open("/etc/passwd", "r")

    def test_workspace_dir_set(self, tmp_path):
        workspace = str(tmp_path)
        module = types.ModuleType("test_mod")
        module.__builtins__ = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
        _sandbox_filesystem(module, workspace)
        assert module.WORKSPACE_DIR == workspace


# ── save_agent_functions ─────────────────────────────────────────────


class TestSaveAgentFunctions:

    def test_saves_function_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))

        functions = [
            {"name": "greet", "function_string": "def greet(name):\n    return f'Hello {name}'", "is_enabled": True},
            {"name": "add", "function_string": "def add(a, b):\n    return a + b", "is_enabled": True},
        ]
        save_agent_functions("TestTool", "t1", functions)

        tool_dir = tmp_path / "TestTool_t1"
        assert tool_dir.exists()
        assert (tool_dir / "greet.py").exists()
        assert (tool_dir / "add.py").exists()

    def test_skips_disabled_functions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))

        functions = [
            {"name": "active", "function_string": "def active(): pass", "is_enabled": True},
            {"name": "disabled", "function_string": "def disabled(): pass", "is_enabled": False},
            {"name": "deleted", "function_string": "def deleted(): pass", "is_enabled": True, "is_deleted": True},
        ]
        save_agent_functions("TestTool", "t1", functions)

        tool_dir = tmp_path / "TestTool_t1"
        assert (tool_dir / "active.py").exists()
        assert not (tool_dir / "disabled.py").exists()
        assert not (tool_dir / "deleted.py").exists()

    def test_cleans_old_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))

        # Create old file
        old_dir = tmp_path / "Tool_t1"
        old_dir.mkdir()
        (old_dir / "old.py").write_text("old code")

        functions = [{"name": "new", "function_string": "def new(): pass", "is_enabled": True}]
        save_agent_functions("Tool", "t1", functions)

        assert not (old_dir / "old.py").exists()
        assert (old_dir / "new.py").exists()


# ── load_agent_functions ─────────────────────────────────────────────


class TestLoadAgentFunctions:

    def test_loads_functions_and_returns_schemas(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))
        monkeypatch.setattr("config.TOOL_SAFE_MODE", False)

        tool_dir = tmp_path / "TestTool_t1"
        tool_dir.mkdir()
        (tool_dir / "greet.py").write_text(
            'def greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello {name}"'
        )

        with patch("services.custom_var_service.get_vars_for_resource", return_value={}):
            schemas, funcs = load_agent_functions("TestTool", "t1")

        assert len(schemas) == 1
        assert schemas[0]["name"] == "greet"
        assert "greet" in funcs

    def test_returns_empty_for_nonexistent_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))

        schemas, funcs = load_agent_functions("Nonexistent", "t1")
        assert schemas == []
        assert funcs == {}

    def test_custom_vars_injected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.agent_service.AGENTS_DIR", str(tmp_path))
        monkeypatch.setattr("config.TOOL_SAFE_MODE", False)

        tool_dir = tmp_path / "Tool_t1"
        tool_dir.mkdir()
        (tool_dir / "check.py").write_text(
            'import os\ndef check_env():\n    """Check env."""\n    return os.getenv("MY_KEY")'
        )

        with patch("services.custom_var_service.get_vars_for_resource", return_value={"MY_KEY": "secret"}):
            schemas, funcs = load_agent_functions("Tool", "t1")

        result = funcs["check_env"]()
        assert result == "secret"


# ── run_agent_loop ───────────────────────────────────────────────────


class TestRunAgentLoop:

    @pytest.mark.asyncio
    async def test_no_tools_falls_back_to_chat_stream(self):
        """When no tools loaded, falls back to regular chat_stream."""
        async def mock_stream(messages, model, system_prompt):
            yield {"type": "text", "text": "Hello from chat"}
            yield {"type": "usage", "model": "test", "input_tokens": 5, "output_tokens": 3}

        with patch("services.agent_service.load_agent_functions", return_value=([], {})), \
             patch("services.agent_service.chat_stream", side_effect=mock_stream), \
             patch("services.agent_service.init_artifact_context"), \
             patch("services.agent_service.collect_artifacts", return_value=[]):
            chunks = []
            async for chunk in run_agent_loop("Hello", "Tool", "t1", "test-model"):
                chunks.append(chunk)

        text_chunks = [c for c in chunks if c.get("type") == "text"]
        assert any("Hello from chat" in c["text"] for c in text_chunks)

    @pytest.mark.asyncio
    async def test_single_iteration_text_only(self):
        """Agent loop with tools but LLM returns text only (no tool_use)."""
        mock_provider = MagicMock()
        mock_provider.call_with_tools = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Just text, no tools needed"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
            "model": "test",
        })

        with patch("services.agent_service.load_agent_functions", return_value=(
            [{"name": "search", "description": "Search", "input_schema": {"type": "object", "properties": {}}}],
            {"search": lambda: "result"},
        )), \
             patch("services.agent_service.get_provider_for_model", return_value=mock_provider), \
             patch("services.agent_service.init_artifact_context"), \
             patch("services.agent_service.collect_artifacts", return_value=[]):
            chunks = []
            async for chunk in run_agent_loop("Hello", "Tool", "t1", "test-model"):
                chunks.append(chunk)

        text_chunks = [c for c in chunks if c.get("type") == "text"]
        assert any("Just text" in c["text"] for c in text_chunks)
        usage_chunks = [c for c in chunks if c.get("type") == "usage"]
        assert len(usage_chunks) == 1

    @pytest.mark.asyncio
    async def test_tool_use_loop(self):
        """Agent loop calls tool and continues."""
        call_count = 0

        async def mock_call_with_tools(messages, tools, model, system):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": [
                        {"type": "text", "text": "Let me search..."},
                        {"type": "tool_use", "id": "call1", "name": "search", "input": {"q": "test"}},
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 8},
                    "stop_reason": "tool_use",
                    "model": "test",
                }
            else:
                return {
                    "content": [{"type": "text", "text": "Found the answer!"}],
                    "usage": {"input_tokens": 15, "output_tokens": 5},
                    "stop_reason": "end_turn",
                    "model": "test",
                }

        mock_provider = MagicMock()
        mock_provider.call_with_tools = mock_call_with_tools

        def sync_search(q=""):
            return f"Results for: {q}"

        with patch("services.agent_service.load_agent_functions", return_value=(
            [{"name": "search", "description": "Search", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}],
            {"search": sync_search},
        )), \
             patch("services.agent_service.get_provider_for_model", return_value=mock_provider), \
             patch("services.agent_service.init_artifact_context"), \
             patch("services.agent_service.collect_artifacts", return_value=[]), \
             patch("services.agent_service._auto_artifact_result", side_effect=lambda x: x):
            chunks = []
            async for chunk in run_agent_loop("Find info", "Tool", "t1", "test-model"):
                chunks.append(chunk)

        tool_calls = [c for c in chunks if c.get("type") == "tool_call"]
        tool_results = [c for c in chunks if c.get("type") == "tool_result"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "search"
        assert len(tool_results) == 1
        assert "Results for: test" in tool_results[0]["result"]
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_stop_check_halts_loop(self):
        """stop_check callback halts the agent loop."""
        stopped = False

        def stop_check():
            return stopped

        async def mock_call_with_tools(messages, tools, model, system):
            nonlocal stopped
            stopped = True
            return {
                "content": [
                    {"type": "tool_use", "id": "c1", "name": "search", "input": {}},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "stop_reason": "tool_use",
                "model": "test",
            }

        mock_provider = MagicMock()
        mock_provider.call_with_tools = mock_call_with_tools

        with patch("services.agent_service.load_agent_functions", return_value=(
            [{"name": "search", "description": "S", "input_schema": {"type": "object", "properties": {}}}],
            {"search": lambda: "r"},
        )), \
             patch("services.agent_service.get_provider_for_model", return_value=mock_provider), \
             patch("services.agent_service.init_artifact_context"), \
             patch("services.agent_service.collect_artifacts", return_value=[]):
            chunks = []
            async for chunk in run_agent_loop("x", "T", "t1", "m", stop_check=stop_check):
                chunks.append(chunk)

        # Loop should have stopped - check we got usage
        usage = [c for c in chunks if c.get("type") == "usage"]
        assert len(usage) == 1

    @pytest.mark.asyncio
    async def test_tool_execution_error_handled(self):
        """Tool execution errors are returned as error messages, not raised."""
        call_count = 0

        async def mock_call_with_tools(messages, tools, model, system):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": [
                        {"type": "tool_use", "id": "c1", "name": "bad_tool", "input": {}},
                    ],
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                    "stop_reason": "tool_use",
                    "model": "test",
                }
            return {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "stop_reason": "end_turn",
                "model": "test",
            }

        mock_provider = MagicMock()
        mock_provider.call_with_tools = mock_call_with_tools

        def bad_tool():
            raise ValueError("Tool broke")

        with patch("services.agent_service.load_agent_functions", return_value=(
            [{"name": "bad_tool", "description": "B", "input_schema": {"type": "object", "properties": {}}}],
            {"bad_tool": bad_tool},
        )), \
             patch("services.agent_service.get_provider_for_model", return_value=mock_provider), \
             patch("services.agent_service.init_artifact_context"), \
             patch("services.agent_service.collect_artifacts", return_value=[]), \
             patch("services.agent_service._auto_artifact_result", side_effect=lambda x: x):
            chunks = []
            async for chunk in run_agent_loop("x", "T", "t1", "m"):
                chunks.append(chunk)

        tool_results = [c for c in chunks if c.get("type") == "tool_result"]
        assert len(tool_results) >= 1
        assert "Error" in tool_results[0]["result"] or "error" in tool_results[0]["result"].lower()
