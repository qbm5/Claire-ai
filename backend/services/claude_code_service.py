import os
import json
import asyncio
import subprocess
import threading
import time
import logging
from typing import AsyncGenerator, Callable, Optional

from services.custom_var_service import get_vars_for_resource
import config

logger = logging.getLogger(__name__)

CLAUDE_CODE_TOOLS = [
    "Bash", "Read", "Edit", "Write", "Glob", "Grep",
    "WebFetch", "WebSearch", "TodoRead", "TodoWrite", "NotebookEdit",
]

_SENTINEL = object()


async def run_claude_code(
    prompt: str,
    tool: dict,
    run_id: str = "",
    step_id: str = "",
    stop_check: Optional[Callable[[], bool]] = None,
) -> AsyncGenerator[dict, None]:
    """Run Claude Code CLI in headless mode and stream events.

    Uses subprocess.Popen with a reader thread to avoid Windows asyncio
    subprocess limitations. Lines are pushed to an asyncio.Queue for
    consumption by the async generator.
    """
    cmd = _build_command(prompt, tool)
    env = _build_env(tool)
    working_dir = tool.get("claude_code_working_dir", "").strip() or None
    timeout_s = tool.get("claude_code_timeout", 600) or 600

    logger.info(f"[ClaudeCode] Starting: cwd={working_dir}, timeout={timeout_s}s, cmd_len={len(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=working_dir,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        yield {"type": "error", "text": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"}
        return
    except OSError as e:
        yield {"type": "error", "text": f"Failed to start Claude CLI: {e}"}
        return

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _reader():
        """Read stdout lines in a background thread and push to queue."""
        try:
            for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    loop.call_soon_threadsafe(queue.put_nowait, line)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, f'{{"type":"_error","text":"{e}"}}')
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    total_input_tokens = 0
    total_output_tokens = 0
    deadline = time.monotonic() + timeout_s

    try:
        while True:
            if stop_check and stop_check():
                _kill_process(process)
                yield {"type": "error", "text": "Execution stopped by user."}
                break

            if time.monotonic() > deadline:
                _kill_process(process)
                yield {"type": "error", "text": f"Claude Code timed out after {timeout_s}s"}
                break

            try:
                line = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if line is _SENTINEL:
                break

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            for chunk in _parse_event(event):
                if chunk.get("type") == "usage_internal":
                    total_input_tokens += chunk.get("input_tokens", 0)
                    total_output_tokens += chunk.get("output_tokens", 0)
                elif chunk.get("type") == "text":
                    yield chunk
                else:
                    yield chunk

    except Exception as e:
        yield {"type": "error", "text": f"Stream error: {e}"}

    # Wait for process to finish
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_process(process)

    reader_thread.join(timeout=5)

    if process.returncode and process.returncode != 0:
        try:
            stderr_text = process.stderr.read().decode("utf-8", errors="replace").strip()
            if stderr_text and "error" in stderr_text.lower():
                yield {"type": "error", "text": f"Claude CLI error (exit {process.returncode}): {stderr_text[:500]}"}
        except Exception:
            pass

    yield {
        "type": "usage",
        "model": "claude-code",
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }


def _build_command(prompt: str, tool: dict) -> list[str]:
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]

    if tool.get("claude_code_bare", True):
        cmd.append("--bare")

    allowed = tool.get("claude_code_allowed_tools", [])
    if allowed:
        cmd.extend(["--allowedTools", ",".join(allowed)])

    perm_mode = tool.get("claude_code_permission_mode", "default")
    if perm_mode in ("acceptEdits", "dontAsk"):
        cmd.extend(["--permission-mode", perm_mode])

    system_prompt = tool.get("system_prompt", "").strip()
    if system_prompt:
        sp_mode = tool.get("claude_code_system_prompt_mode", "append")
        if sp_mode == "replace":
            cmd.extend(["--system-prompt", system_prompt])
        else:
            cmd.extend(["--append-system-prompt", system_prompt])

    max_turns = tool.get("claude_code_max_turns", 0)
    if max_turns and max_turns > 0:
        cmd.extend(["--max-turns", str(max_turns)])

    json_schema = tool.get("claude_code_json_schema", "").strip()
    if json_schema:
        cmd.extend(["--output-format", "json", "--json-schema", json_schema])

    mcp_config = tool.get("claude_code_mcp_config", "").strip()
    if mcp_config:
        cmd.extend(["--mcp-config", mcp_config])

    return cmd


def _build_env(tool: dict) -> dict:
    env = os.environ.copy()

    tool_id = tool.get("id", "")
    if tool_id:
        custom_vars = get_vars_for_resource("tool", tool_id)
        env.update(custom_vars)

    if "ANTHROPIC_API_KEY" not in env or not env.get("ANTHROPIC_API_KEY"):
        api_key = getattr(config, "ANTHROPIC_API_KEY", "")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key

    return env


def _kill_process(process):
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass


def _parse_event(event: dict) -> list[dict]:
    """Parse a single stream-json line into normalized event(s)."""
    results = []
    event_type = event.get("type", "")

    if event_type == "assistant":
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    results.append({"type": "text", "text": text})
            elif block.get("type") == "tool_use":
                results.append({
                    "type": "tool_call",
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })

    elif event_type == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                results.append({"type": "text", "text": text})

    elif event_type == "content_block_start":
        cb = event.get("content_block", {})
        if cb.get("type") == "tool_use":
            results.append({
                "type": "tool_call",
                "name": cb.get("name", ""),
                "input": cb.get("input", {}),
            })

    elif event_type == "tool_result":
        content = event.get("content", "")
        name = event.get("tool_name", event.get("name", "tool"))
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        results.append({
            "type": "tool_result",
            "name": name,
            "result": str(content)[:2000],
        })

    elif event_type == "result":
        usage = event.get("usage", {})
        if usage:
            results.append({
                "type": "usage_internal",
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            })
        result_text = event.get("result", "")
        if result_text and isinstance(result_text, str):
            results.append({"type": "text", "text": result_text})

    elif event_type == "system":
        subtype = event.get("subtype", "")
        if subtype == "api_retry":
            attempt = event.get("attempt", 0)
            max_retries = event.get("max_retries", 0)
            results.append({"type": "text", "text": f"\n[Retrying API call {attempt}/{max_retries}...]\n"})
        elif subtype == "error":
            results.append({"type": "error", "text": event.get("message", "Unknown system error")})

    return results
