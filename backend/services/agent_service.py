"""
Agent service - Claude tool_use agentic loop.
Loads Python functions from data/agents/{tool_name}_{tool_id}/,
inspects signatures to generate Claude tool JSON schemas,
and runs the agentic loop until Claude returns a text-only response.
Optionally connects to MCP servers for additional tools.
"""

import os
import sys
import json
import inspect
import asyncio
import importlib.util
from contextlib import AsyncExitStack
from typing import Any, AsyncGenerator

import logging

import subprocess as _real_subprocess
import types

import re as _re

import config as _config
from config import AGENTS_DIR, DEFAULT_MODEL, AGENT_FUNCTION_TIMEOUT
from services.llm import get_provider_for_model, chat_stream
from services.artifact_service import save_artifact, save_link, init_artifact_context, collect_artifacts

logger = logging.getLogger(__name__)

# Extensions that should be auto-detected as artifacts when returned by tool functions
_ARTIFACT_EXTENSIONS = {
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.ogv',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
    '.pdf', '.csv', '.xlsx', '.xls', '.docx', '.pptx', '.zip',
}

# Regex to find file paths in a result string (Windows or Unix absolute paths)
_FILE_PATH_RE = _re.compile(
    r'(?:[A-Za-z]:[\\\/]|[\/])'   # drive letter + separator OR leading /
    r'[^\s<>"\'|*?\n]+'           # path characters
)


def _auto_artifact_result(result: str) -> str:
    """Scan a tool result string for file paths with known extensions.

    For each path that exists on disk, call save_artifact() to register the
    file as an artifact (so the frontend renders a player/card in the artifact
    tray), but leave the original text unchanged so the agent response text
    is preserved above the media player.
    """
    if not isinstance(result, str):
        return result

    for match in _FILE_PATH_RE.finditer(result):
        path = match.group(0).rstrip('.,;:)')
        # Normalise Windows backslashes for os.path
        norm = os.path.normpath(path)
        _, ext = os.path.splitext(norm)
        if ext.lower() not in _ARTIFACT_EXTENSIONS:
            continue
        if not os.path.isfile(norm):
            continue
        try:
            url = save_artifact(norm)
            logger.info("[Agent] Auto-artifact: %s -> %s", path, url)
        except Exception as e:
            logger.warning("[Agent] Auto-artifact failed for %s: %s", path, e)

    return result


def _make_sandboxed_os_module(custom_vars: dict):
    """Create an os module proxy with environ restricted to only tool custom variables.

    Prevents tool code from accessing system environment variables (API keys, secrets, etc.)
    via os.environ. Only the tool's own custom variables are exposed.
    """
    import os as _real_os

    mod = types.ModuleType("os")
    # Copy everything from real os
    for attr in dir(_real_os):
        if not attr.startswith("__"):
            setattr(mod, attr, getattr(_real_os, attr))

    # Replace environ with a dict containing only the tool's custom vars
    mod.environ = dict(custom_vars)
    # Also override os.getenv to use the sandboxed environ
    mod.getenv = lambda key, default=None: mod.environ.get(key, default)

    return mod


def _install_sandboxed_import(module, sandboxed_os):
    """Override __import__ in the module's builtins so `import os` inside function
    bodies returns the sandboxed os module instead of the real one.

    This is necessary because `import os` inside a function resolves from
    sys.modules['os'] (the real one), bypassing any module-level patching.
    """
    _real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _sandboxed_import(name, *args, **kwargs):
        if name == "os":
            return sandboxed_os
        return _real_import(name, *args, **kwargs)

    # module.__builtins__ can be a dict or a module
    if isinstance(getattr(module, '__builtins__', None), dict):
        module.__builtins__['__import__'] = _sandboxed_import
    else:
        module.__builtins__ = {'__import__': _sandboxed_import}
        # Copy other builtins so tool code can use print, len, etc.
        import builtins
        for attr in dir(builtins):
            if attr != '__import__':
                module.__builtins__.setdefault(attr, getattr(builtins, attr))


def _sandbox_filesystem(module, workspace_dir: str):
    """Restrict filesystem operations to workspace_dir.

    Patches open, os file ops, pathlib.Path, and shutil in the module so that
    all path arguments are resolved and validated against the allowed directory.
    """
    import builtins as _builtins
    import pathlib as _real_pathlib
    import shutil as _real_shutil

    workspace = os.path.realpath(workspace_dir)
    os.makedirs(workspace, exist_ok=True)

    def _validate_path(p) -> str:
        """Resolve path and ensure it's within the workspace."""
        resolved = os.path.realpath(os.path.join(workspace, str(p)))
        if not resolved.startswith(workspace + os.sep) and resolved != workspace:
            raise PermissionError(
                f"Access denied: path '{p}' is outside the allowed workspace. "
                f"Tool code can only access files within its workspace directory."
            )
        return resolved

    # Sandboxed open()
    _real_open = _builtins.open

    def _sandboxed_open(file, mode='r', *args, **kwargs):
        return _real_open(_validate_path(file), mode, *args, **kwargs)

    # Inject into module builtins
    if isinstance(getattr(module, '__builtins__', None), dict):
        module.__builtins__['open'] = _sandboxed_open
    else:
        module.__builtins__ = {}
        import builtins
        for attr in dir(builtins):
            module.__builtins__[attr] = getattr(builtins, attr)
        module.__builtins__['open'] = _sandboxed_open

    # Patch os module (already sandboxed for environ, now add fs restrictions)
    if hasattr(module, 'os'):
        _mod_os = module.os

        def _wrap_single(fn):
            def wrapper(path, *a, **kw):
                return fn(_validate_path(path), *a, **kw)
            wrapper.__name__ = fn.__name__
            return wrapper

        def _wrap_src_dst(fn):
            def wrapper(src, dst, *a, **kw):
                return fn(_validate_path(src), _validate_path(dst), *a, **kw)
            wrapper.__name__ = fn.__name__
            return wrapper

        for name in ('listdir', 'scandir', 'mkdir', 'makedirs', 'remove',
                     'unlink', 'rmdir', 'stat', 'chmod', 'walk'):
            if hasattr(_mod_os, name):
                setattr(_mod_os, name, _wrap_single(getattr(os, name)))

        for name in ('rename', 'replace', 'link', 'symlink'):
            if hasattr(_mod_os, name):
                setattr(_mod_os, name, _wrap_src_dst(getattr(os, name)))

        # os.path wrappers for resolution (make relative paths resolve from workspace)
        _real_os_path = os.path

        class _SandboxedPath:
            """os.path proxy that resolves paths relative to the workspace."""
            def __getattr__(self, name):
                return getattr(_real_os_path, name)

            def join(self, *args):
                return _real_os_path.join(*args)

            def exists(self, p):
                return _real_os_path.exists(_validate_path(p))

            def isfile(self, p):
                return _real_os_path.isfile(_validate_path(p))

            def isdir(self, p):
                return _real_os_path.isdir(_validate_path(p))

            def realpath(self, p):
                return _validate_path(p)

            def abspath(self, p):
                return _validate_path(p)

            def getsize(self, p):
                return _real_os_path.getsize(_validate_path(p))

        _mod_os.path = _SandboxedPath()
        _mod_os.getcwd = lambda: workspace
        _mod_os.chdir = lambda p: None  # no-op

        # os.open (low-level file descriptor)
        _real_os_open = os.open
        def _sandboxed_os_open(path, flags, mode=0o777, *a, **kw):
            return _real_os_open(_validate_path(path), flags, mode, *a, **kw)
        _mod_os.open = _sandboxed_os_open

    # Patch shutil if imported
    if hasattr(module, 'shutil'):
        _mod_shutil = types.ModuleType("shutil")
        for attr in dir(_real_shutil):
            if not attr.startswith("__"):
                setattr(_mod_shutil, attr, getattr(_real_shutil, attr))

        def _safe_copy(src, dst, *a, **kw):
            return _real_shutil.copy2(_validate_path(src), _validate_path(dst), *a, **kw)

        def _safe_copytree(src, dst, *a, **kw):
            return _real_shutil.copytree(_validate_path(src), _validate_path(dst), *a, **kw)

        def _safe_rmtree(path, *a, **kw):
            return _real_shutil.rmtree(_validate_path(path), *a, **kw)

        def _safe_move(src, dst, *a, **kw):
            return _real_shutil.move(_validate_path(src), _validate_path(dst), *a, **kw)

        _mod_shutil.copy = _safe_copy
        _mod_shutil.copy2 = _safe_copy
        _mod_shutil.copytree = _safe_copytree
        _mod_shutil.rmtree = _safe_rmtree
        _mod_shutil.move = _safe_move
        module.shutil = _mod_shutil

    # Patch pathlib if imported
    if hasattr(module, 'pathlib') or hasattr(module, 'Path'):
        class SandboxedPath(_real_pathlib.Path):
            """Path subclass that validates all paths against the workspace."""
            _flavour = _real_pathlib.PurePosixPath._flavour if os.name != 'nt' else _real_pathlib.PureWindowsPath._flavour

            def __new__(cls, *args, **kwargs):
                p = super().__new__(cls, *args, **kwargs)
                _validate_path(str(p))
                return p

        sandboxed_pathlib = types.ModuleType("pathlib")
        for attr in dir(_real_pathlib):
            if not attr.startswith("__"):
                setattr(sandboxed_pathlib, attr, getattr(_real_pathlib, attr))
        sandboxed_pathlib.Path = SandboxedPath

        if hasattr(module, 'pathlib'):
            module.pathlib = sandboxed_pathlib
        if hasattr(module, 'Path'):
            module.Path = SandboxedPath

    # Provide workspace path as a module global for convenience
    module.WORKSPACE_DIR = workspace


def _make_tracked_subprocess_module():
    """Create a subprocess module proxy that routes run/Popen through the subprocess manager."""
    from services.subprocess_manager import safe_run, _register, _assign_to_job, _unregister

    mod = types.ModuleType("subprocess")
    # Copy everything from real subprocess
    for attr in dir(_real_subprocess):
        if not attr.startswith("__"):
            setattr(mod, attr, getattr(_real_subprocess, attr))

    # Override run() to use safe_run, stripping subprocess.run-specific kwargs
    # that safe_run/Popen don't accept
    def tracked_run(args, **kwargs):
        timeout = kwargs.pop("timeout", None)
        check = kwargs.pop("check", False)
        input_data = kwargs.pop("input", None)
        result = safe_run(args, timeout=timeout, **kwargs)
        # Feed input via communicate if provided (safe_run already calls communicate)
        # Handle check after execution, same as subprocess.run
        if check and result.returncode:
            raise _real_subprocess.CalledProcessError(
                result.returncode, args, output=result.stdout, stderr=result.stderr
            )
        return result

    # Override Popen to register/track
    _OrigPopen = _real_subprocess.Popen
    class TrackedPopen(_OrigPopen):
        def __init__(self, args, **kwargs):
            # Always pipe stdin so interactive prompts get EOF and fail fast
            # instead of hanging forever waiting for user input
            if "stdin" not in kwargs or kwargs["stdin"] is None:
                kwargs["stdin"] = _real_subprocess.DEVNULL
            super().__init__(args, **kwargs)
            _register(self)
            _assign_to_job(self)

        def wait(self, timeout=None):
            try:
                return super().wait(timeout=timeout)
            finally:
                _unregister(self.pid)

        def communicate(self, input=None, timeout=None):
            try:
                return super().communicate(input=input, timeout=timeout)
            finally:
                _unregister(self.pid)

    mod.run = tracked_run
    mod.Popen = TrackedPopen
    return mod

# Agent loop limits
MAX_AGENT_ITERATIONS = 30
TOKEN_BUDGET = 500_000

AGENT_SYSTEM_ADDENDUM = (
    "\n\nCRITICAL RULES:"
    "\n1. Only call tools that are directly necessary to fulfill the user's request."
    "\n2. NEVER invent, guess, or fabricate input values (file paths, URLs, directories, etc.) that were not explicitly provided by the user or returned by a previous tool call."
    "\n3. Do NOT make speculative, redundant, or exploratory tool calls beyond what was asked."
    "\n4. If the user asks to scan ONE directory, call the tool ONCE with ONLY that directory. Do not scan additional directories."
    "\n5. NEVER run interactive commands that prompt for user input — stdin is not available. "
    "Use non-interactive flags (e.g. --yes, -y, --non-interactive, --default) or fully specify all options via CLI arguments. "
    "Examples: use 'npm create vite@latest myapp -- --template vue-ts' (fully specified), NOT 'npm create vite@latest' (prompts for choices)."
)


def _python_type_to_json_type(annotation) -> str:
    if annotation in (str, inspect.Parameter.empty):
        return "string"
    elif annotation in (int,):
        return "integer"
    elif annotation in (float,):
        return "number"
    elif annotation in (bool,):
        return "boolean"
    elif annotation in (list, list[str]):
        return "array"
    return "string"


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Extract parameter descriptions from a docstring.
    Supports :param name: style AND Google-style Args: blocks."""
    import re
    params = {}
    if not docstring:
        return params
    # RST-style  :param name: description
    for match in re.finditer(r":param\s+(\w+)\s*:\s*(.+?)(?=\n\s*:|$)", docstring, re.DOTALL):
        params[match.group(1)] = match.group(2).strip()
    if params:
        return params
    # Google-style  Args:\n    name: description (possibly multi-line indented)
    args_match = re.search(r"(?:^|\n)\s*Args:\s*\n((?:[ \t]+\S.*\n?)+)", docstring)
    if args_match:
        block = args_match.group(1)
        for m in re.finditer(r"^[ \t]+(\w+)\s*(?:\(.*?\))?\s*:\s*(.+?)(?=\n[ \t]+\w+\s*(?:\(.*?\))?\s*:|$)", block, re.MULTILINE | re.DOTALL):
            desc_lines = m.group(2).strip().splitlines()
            desc = " ".join(line.strip() for line in desc_lines)
            params[m.group(1)] = desc
    return params


def _func_to_tool_schema(fn) -> dict:
    """Convert a Python function to a Claude tool JSON schema."""
    sig = inspect.signature(fn)
    param_docs = _parse_param_docs(fn.__doc__ or "")
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        json_type = _python_type_to_json_type(param.annotation)
        desc = param_docs.get(name, name)
        prop = {"type": json_type, "description": desc}
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "name": fn.__name__,
        "description": fn.__doc__ or fn.__name__,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def load_agent_functions(tool_name: str, tool_id: str) -> tuple[list[dict], dict]:
    """Load Python functions from the agent directory.

    Returns (tool_schemas, functions_by_name).
    """
    tool_dir = os.path.join(AGENTS_DIR, f"{tool_name}_{tool_id}")
    schemas = []
    funcs_by_name = {}

    if not os.path.isdir(tool_dir):
        return schemas, funcs_by_name

    # Load scoped custom variables for this tool
    from services.custom_var_service import get_vars_for_resource
    custom_vars = get_vars_for_resource("tool", tool_id)

    for fname in os.listdir(tool_dir):
        if not fname.endswith(".py"):
            continue

        path = os.path.join(tool_dir, fname)
        module_name = f"agent_{tool_name}_{tool_id}_{fname[:-3]}"

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        # Inject custom variables as module globals before execution
        for var_name, var_value in custom_vars.items():
            setattr(module, var_name, var_value)
        setattr(module, 'get_var', lambda name, _cv=custom_vars: _cv.get(name, ""))

        # Build sandboxed os module BEFORE exec so module-level `import os` is caught
        sandboxed_os = _make_sandboxed_os_module(custom_vars)
        _install_sandboxed_import(module, sandboxed_os)

        spec.loader.exec_module(module)

        # Post-exec: also patch any already-resolved os references
        if hasattr(module, 'os') and module.os is not sandboxed_os:
            module.os = sandboxed_os
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if obj is os.environ:
                setattr(module, attr_name, sandboxed_os.environ)
            elif obj is os.getenv:
                setattr(module, attr_name, sandboxed_os.getenv)

        # Inject artifact functions into agent module globals
        setattr(module, 'save_artifact', save_artifact)
        setattr(module, 'save_link', save_link)

        # Patch subprocess module in agent code so processes are tracked
        tracked_subprocess = _make_tracked_subprocess_module()
        if hasattr(module, 'subprocess'):
            module.subprocess = tracked_subprocess
        # Also patch any imported references (e.g. from subprocess import run)
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if obj is _real_subprocess.run:
                setattr(module, attr_name, tracked_subprocess.run)
            elif obj is _real_subprocess.Popen:
                setattr(module, attr_name, tracked_subprocess.Popen)

        # In Safe Mode, sandbox filesystem access to a workspace directory
        if _config.TOOL_SAFE_MODE:
            workspace = os.path.join(tool_dir, "workspace")
            _sandbox_filesystem(module, workspace)

        for _, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ != spec.name:
                continue
            schema = _func_to_tool_schema(fn)
            schemas.append(schema)
            funcs_by_name[fn.__name__] = fn

    return schemas, funcs_by_name


def save_agent_functions(tool_name: str, tool_id: str, functions: list[dict]):
    """Save agent function files to disk."""
    import shutil
    tool_dir = os.path.join(AGENTS_DIR, f"{tool_name}_{tool_id}")

    os.makedirs(AGENTS_DIR, exist_ok=True)
    if os.path.isdir(tool_dir):
        shutil.rmtree(tool_dir)
    os.makedirs(tool_dir, exist_ok=True)

    for fn in functions:
        if not fn.get("is_enabled", True) or fn.get("is_deleted", False):
            continue
        name = fn.get("name", "")
        code = fn.get("function_string", "").rstrip()
        if not name or not code:
            continue
        file_path = os.path.join(tool_dir, f"{name}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
            if not code.endswith("\n"):
                f.write("\n")


async def run_agent_loop(
    prompt: str,
    tool_name: str,
    tool_id: str,
    model: str = "",
    system_prompt: str = "",
    mcp_servers: list[dict] | None = None,
    run_id: str = "",
    step_id: str = "",
    stop_check: Any = None,
) -> AsyncGenerator[dict, None]:
    """Run the Claude tool_use agentic loop.

    Yields dicts: {"type": "text", "text": ...} or {"type": "tool_call", ...} or {"type": "usage", ...}
    """
    model = model or DEFAULT_MODEL

    # Initialize artifact tracking for this run
    init_artifact_context(run_id or "_tool_test")

    async with AsyncExitStack() as stack:
        # 1. Load Python functions
        schemas, funcs_by_name = load_agent_functions(tool_name, tool_id)

        # 2. Connect to MCP servers and collect their tools
        mcp_tool_to_session: dict[str, Any] = {}  # tool_name -> ClientSession

        # Resolve MCP server headers from env vars
        from services.custom_var_service import get_vars_for_resource
        from services.template_engine import parse_text
        mcp_custom_vars = get_vars_for_resource("tool", tool_id) if tool_id else {}
        mcp_var_props = [{"name": k, "value": v} for k, v in mcp_custom_vars.items()]

        for cfg in (mcp_servers or []):
            if not cfg.get("is_enabled", True):
                continue
            # Resolve header templates (e.g. "Bearer {{API_TOKEN}}")
            raw_headers = cfg.get("headers") or []
            if raw_headers and mcp_var_props:
                resolved = {}
                for pair in raw_headers:
                    if isinstance(pair, dict) and pair.get("key"):
                        val = parse_text(pair.get("value", ""), mcp_var_props)
                        resolved[pair["key"]] = val
                cfg = {**cfg, "resolved_headers": resolved}
            try:
                from services.mcp_client import connect_mcp, list_mcp_tools
                session = await stack.enter_async_context(connect_mcp(cfg))
                tools = await list_mcp_tools(session)
                allowed = cfg.get("allowed_tools") or []
                for t in tools:
                    if allowed and t["name"] not in allowed:
                        continue
                    schemas.append(t)
                    mcp_tool_to_session[t["name"]] = session
            except Exception as e:
                yield {"type": "error", "text": f"MCP server '{cfg.get('name', '?')}' failed: {e}"}

        # 3. If no tools at all, fall back to regular chat
        if not schemas:
            async for chunk in chat_stream([{"role": "user", "content": prompt}], model, system_prompt):
                yield chunk
            return

        # Append agent guardrails to system prompt
        effective_system = (system_prompt or "") + AGENT_SYSTEM_ADDENDUM

        provider = get_provider_for_model(model)
        logger.info("[Agent] Starting loop — model=%s, %d tool schemas, provider=%s",
                     model, len(schemas), type(provider).__name__)

        if run_id:
            from services.pipeline_logger import run_log
            run_log(run_id, "agent", f"Agent loop started: {len(schemas)} tools, model={model}",
                    step_id=step_id, detail={"tools": [s["name"] for s in schemas]})

        messages = [{"role": "user", "content": prompt}]
        total_input = 0
        total_output = 0

        for iteration in range(MAX_AGENT_ITERATIONS):
            if stop_check and stop_check():
                logger.info("[Agent] Stop requested — exiting loop at iteration %d", iteration + 1)
                if run_id:
                    run_log(run_id, "agent", "Agent loop stopped by user", step_id=step_id, level="warn")
                break

            logger.info("[Agent] Iteration %d — calling LLM with %d messages...", iteration + 1, len(messages))
            if run_id:
                run_log(run_id, "agent", f"Iteration {iteration + 1} — {len(messages)} messages",
                        step_id=step_id)
            try:
                resp = await provider.call_with_tools(messages, schemas, model, effective_system)
            except Exception as e:
                logger.error("[Agent] LLM call failed on iteration %d: %s", iteration + 1, e, exc_info=True)
                if run_id:
                    run_log(run_id, "agent", f"LLM call failed: {e}", step_id=step_id, level="error")
                yield {"type": "error", "text": f"LLM error: {e}"}
                break

            usage = resp.get("usage", {})
            total_input += usage.get("input_tokens", 0)
            total_output += usage.get("output_tokens", 0)

            # Check token budget
            if total_input + total_output > TOKEN_BUDGET:
                yield {"type": "text", "text": f"\n\n[Agent stopped — token budget of {TOKEN_BUDGET:,} exceeded ({total_input + total_output:,} used)]"}
                break

            # Process response blocks (already serialized dicts)
            tool_uses = []
            for block in resp["content"]:
                if block["type"] == "text":
                    yield {"type": "text", "text": block["text"]}
                elif block["type"] == "tool_use":
                    tool_uses.append(block)
                    yield {
                        "type": "tool_call",
                        "name": block["name"],
                        "input": block["input"],
                    }

            logger.info("[Agent] Iteration %d — stop_reason=%s, tool_calls=%s",
                         iteration + 1, resp["stop_reason"],
                         [t["name"] for t in tool_uses] or "none")
            if run_id:
                run_log(run_id, "agent",
                        f"Iteration {iteration + 1} result: stop={resp['stop_reason']}, tools={[t['name'] for t in tool_uses] or 'none'}",
                        step_id=step_id,
                        detail={"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)})

            if resp["stop_reason"] != "tool_use" or not tool_uses:
                logger.info("[Agent] Loop finished — stop_reason=%s", resp["stop_reason"])
                break

            # Deduplicate tool calls — only keep the first call per tool name,
            # skip subsequent duplicate calls (OpenAI models often hallucinate extra calls)
            seen_tools: set[str] = set()
            deduped_tool_uses = []
            skipped_tool_uses = []
            for t in tool_uses:
                if t["name"] not in seen_tools:
                    seen_tools.add(t["name"])
                    deduped_tool_uses.append(t)
                else:
                    skipped_tool_uses.append(t)
            if skipped_tool_uses:
                logger.warning("[Agent] Dropping %d duplicate tool call(s): %s",
                               len(skipped_tool_uses),
                               [(t["name"], t.get("input", {})) for t in skipped_tool_uses])
            tool_uses = deduped_tool_uses

            # Feed the assistant response back as-is (already serialized)
            messages.append({"role": "assistant", "content": resp["content"]})

            tool_results = []
            # First, add results for skipped duplicates so the message history stays valid
            for tool_use in skipped_tool_uses:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": "Skipped: duplicate call — result already provided by the first invocation of this tool.",
                })

            for tool_use in tool_uses:
                # Log input values (truncated) for debugging, not just key names
                input_summary = {}
                if isinstance(tool_use["input"], dict):
                    for k, v in tool_use["input"].items():
                        sv = str(v)
                        input_summary[k] = sv[:200] + "..." if len(sv) > 200 else sv
                logger.info("[Agent] Executing tool '%s' with inputs: %s",
                             tool_use["name"], input_summary)
                # Check MCP tools first, then Python functions
                mcp_session = mcp_tool_to_session.get(tool_use["name"])
                if mcp_session is not None:
                    try:
                        from services.mcp_client import call_mcp_tool
                        result = await call_mcp_tool(mcp_session, tool_use["name"], tool_use["input"])
                    except Exception as e:
                        result = f"Error calling MCP tool '{tool_use['name']}': {e}"
                elif tool_use["name"] in funcs_by_name:
                    fn = funcs_by_name[tool_use["name"]]
                    try:
                        tool_timeout = AGENT_FUNCTION_TIMEOUT
                        if asyncio.iscoroutinefunction(fn):
                            coro = fn(**tool_use["input"])
                        else:
                            coro = asyncio.to_thread(fn, **tool_use["input"])

                        # Run with periodic "still waiting" logs
                        start_t = asyncio.get_event_loop().time()
                        task = asyncio.ensure_future(coro)
                        while not task.done():
                            try:
                                await asyncio.wait_for(asyncio.shield(task), timeout=30)
                            except asyncio.TimeoutError:
                                if task.done():
                                    break
                                elapsed = asyncio.get_event_loop().time() - start_t
                                if elapsed >= tool_timeout:
                                    task.cancel()
                                    raise
                                logger.info("[Agent] Tool '%s' still running... (%.0fs elapsed)", tool_use["name"], elapsed)

                        result = str(task.result())
                    except asyncio.TimeoutError:
                        logger.error("[Agent] Tool '%s' timed out after %ds", tool_use["name"], AGENT_FUNCTION_TIMEOUT)
                        if run_id:
                            run_log(run_id, "tool", f"Tool '{tool_use['name']}' timed out after {AGENT_FUNCTION_TIMEOUT}s",
                                    step_id=step_id, level="error")
                        result = f"Error: function timed out after {AGENT_FUNCTION_TIMEOUT}s"
                    except asyncio.CancelledError:
                        logger.error("[Agent] Tool '%s' was cancelled", tool_use["name"])
                        result = f"Error: function was cancelled"
                    except Exception as e:
                        logger.error("[Agent] Tool '%s' raised: %s", tool_use["name"], e, exc_info=True)
                        if run_id:
                            run_log(run_id, "tool", f"Tool '{tool_use['name']}' error: {e}",
                                    step_id=step_id, level="error")
                        result = f"Error: {e}"
                else:
                    result = f"Error: function '{tool_use['name']}' not found"

                logger.info("[Agent] Tool '%s' returned %d chars", tool_use["name"], len(str(result)))
                if run_id:
                    run_log(run_id, "tool", f"Tool '{tool_use['name']}' returned ({len(str(result))} chars)",
                            step_id=step_id)

                # Auto-detect file paths in the result and convert to artifact URLs
                if isinstance(result, str):
                    result = _auto_artifact_result(result)

                # For the frontend event, always send a string summary
                result_summary = result if isinstance(result, str) else "[structured content]"
                yield {"type": "tool_result", "name": tool_use["name"], "result": result_summary}

                # For the Claude API, pass structured content (list) or string as-is
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

            # Check stop after all tools executed, before next LLM call
            if stop_check and stop_check():
                logger.info("[Agent] Stop requested after tool execution — exiting loop")
                if run_id:
                    run_log(run_id, "agent", "Agent loop stopped by user", step_id=step_id, level="warn")
                break

        logger.info("[Agent] Loop complete — %d total input tokens, %d total output tokens", total_input, total_output)
        if run_id:
            run_log(run_id, "agent", f"Agent loop complete ({total_input + total_output:,} total tokens)",
                    step_id=step_id, detail={"total_input_tokens": total_input, "total_output_tokens": total_output})

        # Collect any artifacts registered by agent functions during this loop
        artifacts = collect_artifacts()
        if artifacts:
            yield {"type": "artifacts", "artifacts": artifacts}

        yield {
            "type": "usage",
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
        }
