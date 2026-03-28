"""WebSocket-to-pylsp stdio bridge.

Spawns a pylsp subprocess per WebSocket connection and translates
between WebSocket text frames (raw JSON-RPC) and Content-Length-framed
stdio that the Language Server Protocol requires.

Uses subprocess.Popen with threaded I/O because asyncio subprocess
pipes are not supported on Windows.
"""

import asyncio
import logging
import shutil
import subprocess
import threading

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def ws_lsp(ws: WebSocket):
    # Verify pylsp is installed
    if not shutil.which("pylsp"):
        await ws.accept()
        await ws.send_text(
            '{"jsonrpc":"2.0","method":"window/showMessage",'
            '"params":{"type":1,"message":"pylsp not found. '
            'Install python-lsp-server: pip install python-lsp-server[rope]"}}'
        )
        await ws.close(1011, "pylsp not found")
        return

    await ws.accept()

    proc = subprocess.Popen(
        ["pylsp", "-v"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logger.info("pylsp started (pid=%s)", proc.pid)

    loop = asyncio.get_event_loop()
    closed = threading.Event()

    # ------------------------------------------------------------------
    # stdout reader thread: reads Content-Length framed LSP messages
    # from pylsp stdout and pushes them to the WebSocket via the event loop.
    # ------------------------------------------------------------------
    def _read_stdout():
        try:
            while not closed.is_set():
                # Read headers until blank line
                headers: dict[str, str] = {}
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        return  # EOF — process exited
                    line_str = line.decode("ascii").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, val = line_str.split(":", 1)
                        headers[key.strip()] = val.strip()

                length = int(headers.get("Content-Length", 0))
                if length <= 0:
                    continue

                body = proc.stdout.read(length)
                if not body:
                    return
                text = body.decode("utf-8")
                logger.info("pylsp→WS: %s", text[:200])
                # Schedule WS send on the event loop
                asyncio.run_coroutine_threadsafe(ws.send_text(text), loop)
        except Exception as exc:
            logger.exception("stdout reader error: %s", exc)
        finally:
            # Signal the main coroutine that stdout is done
            asyncio.run_coroutine_threadsafe(_signal_done(), loop)

    # ------------------------------------------------------------------
    # stderr reader thread: forwards pylsp log output to Python logger.
    # ------------------------------------------------------------------
    def _read_stderr():
        try:
            while not closed.is_set():
                line = proc.stderr.readline()
                if not line:
                    return
                logger.debug("pylsp: %s", line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass

    done_event = asyncio.Event()

    async def _signal_done():
        done_event.set()

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # ------------------------------------------------------------------
    # Main loop: read from WebSocket, write to pylsp stdin.
    # ------------------------------------------------------------------
    try:
        while True:
            # Wait for either a WS message or the stdout thread finishing
            ws_task = asyncio.ensure_future(ws.receive_text())
            done_task = asyncio.ensure_future(done_event.wait())
            finished, pending = await asyncio.wait(
                [ws_task, done_task], return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if done_task in finished:
                break

            data = ws_task.result()
            logger.info("WS→pylsp: %s", data[:200])
            encoded = data.encode("utf-8")
            header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
            proc.stdin.write(header + encoded)
            proc.stdin.flush()
    except WebSocketDisconnect:
        logger.info("LSP WebSocket disconnected by client")
    except Exception as exc:
        logger.exception("LSP bridge error: %s", exc)
    finally:
        closed.set()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        logger.info("pylsp stopped (pid=%s)", proc.pid)
