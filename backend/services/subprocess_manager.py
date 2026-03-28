"""
Subprocess safety manager — three-layer defense for child processes.

Layer 1: Windows Job Object — auto-kills all children when server exits (even on crash)
Layer 2: Process registry + shutdown hooks — graceful cleanup on normal shutdown
Layer 3: safe_run() — per-process timeout with tree-kill + file size monitoring
"""

import os
import sys
import time
import logging
import subprocess
import threading
from typing import Optional

from config import SUBPROCESS_TIMEOUT, SUBPROCESS_MAX_OUTPUT_FILE_MB

logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────

_job_handle = None  # Windows Job Object handle
_active_processes: dict[int, subprocess.Popen] = {}
_lock = threading.Lock()
_on_change_callback = None  # Called when processes are registered/unregistered


def set_on_change(callback):
    """Set a callback invoked whenever the active process list changes.

    The callback receives no arguments and must be safe to call from any thread.
    """
    global _on_change_callback
    _on_change_callback = callback


def _notify_change():
    if _on_change_callback:
        try:
            _on_change_callback()
        except Exception:
            pass


# ── Exceptions ────────────────────────────────────────────────────────

class FileSizeLimitError(Exception):
    """Raised when a subprocess output file exceeds the size limit."""
    pass


# ── Windows Job Object (Layer 1) ─────────────────────────────────────

def init_job_object():
    """Create a Windows Job Object with KILL_ON_JOB_CLOSE.

    When the handle is closed (including on crash), Windows kills all
    processes assigned to the job.  No-op on non-Windows platforms.
    """
    global _job_handle

    if sys.platform != "win32":
        logger.info("[SubprocessMgr] Not Windows — skipping Job Object")
        return

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        # CreateJobObjectW(lpJobAttributes, lpName)
        _job_handle = kernel32.CreateJobObjectW(None, None)
        if not _job_handle:
            logger.error("[SubprocessMgr] CreateJobObjectW failed")
            return

        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        # JobObjectExtendedLimitInformation = 9
        info_class = 9

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        result = kernel32.SetInformationJobObject(
            _job_handle,
            info_class,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not result:
            logger.error("[SubprocessMgr] SetInformationJobObject failed")
            kernel32.CloseHandle(_job_handle)
            _job_handle = None
            return

        logger.info("[SubprocessMgr] Windows Job Object created (KILL_ON_JOB_CLOSE)")

    except Exception as e:
        logger.error("[SubprocessMgr] Failed to create Job Object: %s", e, exc_info=True)
        _job_handle = None


def _assign_to_job(proc: subprocess.Popen):
    """Assign a process to the Job Object so it dies when the server dies."""
    if _job_handle is None or sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Get process handle from pid
        PROCESS_ALL_ACCESS = 0x1F0FFF
        handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
        if handle:
            result = kernel32.AssignProcessToJobObject(_job_handle, handle)
            kernel32.CloseHandle(handle)
            if result:
                logger.debug("[SubprocessMgr] PID %d assigned to Job Object", proc.pid)
            else:
                logger.warning("[SubprocessMgr] AssignProcessToJobObject failed for PID %d", proc.pid)
        else:
            logger.warning("[SubprocessMgr] OpenProcess failed for PID %d", proc.pid)
    except Exception as e:
        logger.warning("[SubprocessMgr] Job assignment failed for PID %d: %s", proc.pid, e)


# ── Process Tree Kill ─────────────────────────────────────────────────

def _kill_process_tree(pid: int):
    """Kill a process and all its children.  Uses taskkill /T /F on Windows."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        logger.info("[SubprocessMgr] Killed process tree PID %d", pid)
    except Exception as e:
        logger.warning("[SubprocessMgr] Failed to kill PID %d: %s", pid, e)


# ── Process Registry (Layer 2) ───────────────────────────────────────

def _register(proc: subprocess.Popen):
    with _lock:
        _active_processes[proc.pid] = proc
    logger.debug("[SubprocessMgr] Registered PID %d (active: %d)", proc.pid, len(_active_processes))
    _notify_change()


def _unregister(pid: int):
    with _lock:
        _active_processes.pop(pid, None)
    logger.debug("[SubprocessMgr] Unregistered PID %d (active: %d)", pid, len(_active_processes))
    _notify_change()


# ── safe_run() (Layer 3) ─────────────────────────────────────────────

def _detect_output_file(args: list[str]) -> Optional[str]:
    """Try to detect the output file from the command args.

    Heuristic: last argument that looks like a file path (has an extension).
    Skips args that look like flags or '-' (stdout).
    """
    for arg in reversed(args):
        if arg.startswith("-") or arg == "-":
            continue
        _, ext = os.path.splitext(arg)
        if ext:
            return arg
    return None


def safe_run(
    args: list[str],
    timeout: Optional[int] = None,
    max_output_file_mb: Optional[int] = None,
    output_file: Optional[str] = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Drop-in replacement for subprocess.run() with safety rails.

    - Assigns child to Windows Job Object (auto-kill on server crash)
    - Tracks process in registry (killed on graceful shutdown)
    - Monitors output file size in a daemon thread
    - Tree-kills on timeout or size violation
    - Deletes oversized output files

    Args:
        args: Command and arguments (same as subprocess.run)
        timeout: Seconds before killing (default: SUBPROCESS_TIMEOUT)
        max_output_file_mb: Max output file size in MB (default: SUBPROCESS_MAX_OUTPUT_FILE_MB)
        output_file: Explicit output file path. Auto-detected from args if not provided.
        **kwargs: Passed through to Popen (e.g. capture_output, text, cwd)

    Returns:
        subprocess.CompletedProcess

    Raises:
        subprocess.TimeoutExpired: If the process exceeds the timeout
        FileSizeLimitError: If the output file exceeds the size limit
    """
    if timeout is None:
        timeout = SUBPROCESS_TIMEOUT
    if max_output_file_mb is None:
        max_output_file_mb = SUBPROCESS_MAX_OUTPUT_FILE_MB

    # Resolve output file
    monitored_file = output_file or _detect_output_file(args)

    # Handle capture_output kwarg (Popen doesn't accept it directly)
    capture_output = kwargs.pop("capture_output", False)
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    # Prevent interactive prompts from hanging — redirect stdin to DEVNULL
    if "stdin" not in kwargs or kwargs["stdin"] is None:
        kwargs["stdin"] = subprocess.DEVNULL

    # Start the process
    proc = subprocess.Popen(args, **kwargs)
    _register(proc)
    _assign_to_job(proc)

    # File-size monitoring state
    killed_for_size = threading.Event()

    def _monitor_file_size():
        """Daemon thread: poll output file size every 2s, kill if over limit."""
        limit_bytes = max_output_file_mb * 1024 * 1024
        while proc.poll() is None:
            time.sleep(2)
            if monitored_file and os.path.exists(monitored_file):
                try:
                    size = os.path.getsize(monitored_file)
                    if size > limit_bytes:
                        size_mb = size / (1024 * 1024)
                        logger.warning(
                            "[SubprocessMgr] PID %d output file %.1f MB exceeds %d MB limit — killing",
                            proc.pid, size_mb, max_output_file_mb,
                        )
                        killed_for_size.set()
                        _kill_process_tree(proc.pid)
                        return
                except OSError:
                    pass

    if monitored_file:
        monitor_thread = threading.Thread(target=_monitor_file_size, daemon=True)
        monitor_thread.start()

    # Wait with timeout
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("[SubprocessMgr] PID %d timed out after %ds — killing tree", proc.pid, timeout)
        _kill_process_tree(proc.pid)
        # Read any remaining output
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = None, None
        _unregister(proc.pid)
        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    finally:
        _unregister(proc.pid)

    # Check if killed for file size
    if killed_for_size.is_set():
        # Try to delete the oversized file
        if monitored_file and os.path.exists(monitored_file):
            try:
                size_mb = os.path.getsize(monitored_file) / (1024 * 1024)
                os.remove(monitored_file)
                logger.info("[SubprocessMgr] Deleted oversized file: %s (%.1f MB)", monitored_file, size_mb)
            except OSError as e:
                logger.warning("[SubprocessMgr] Could not delete oversized file %s: %s", monitored_file, e)
        raise FileSizeLimitError(
            f"Output file exceeded {max_output_file_mb} MB limit — process killed and file deleted"
        )

    return subprocess.CompletedProcess(
        args=args,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ── Dashboard helpers ─────────────────────────────────────────────────

def get_status() -> dict:
    """Return current subprocess manager state for the dashboard."""
    with _lock:
        processes = []
        for pid, proc in _active_processes.items():
            processes.append({
                "pid": pid,
                "command": proc.args if isinstance(proc.args, str) else " ".join(proc.args[:4]),
                "running": proc.poll() is None,
            })
    return {
        "job_object_active": _job_handle is not None,
        "active_count": len(processes),
        "processes": processes,
    }


def kill_process(pid: int) -> bool:
    """Kill a specific tracked process by PID. Returns True if found and killed."""
    with _lock:
        proc = _active_processes.get(pid)
    if proc is None:
        return False
    _kill_process_tree(pid)
    _unregister(pid)
    return True


# ── Shutdown (Layer 2) ───────────────────────────────────────────────

def shutdown():
    """Kill all tracked processes and close the Job Object.

    Called from lifespan shutdown and atexit.  Safe to call multiple times.
    """
    global _job_handle

    with _lock:
        pids = list(_active_processes.keys())

    if pids:
        logger.info("[SubprocessMgr] Shutting down — killing %d active processes: %s", len(pids), pids)
        for pid in pids:
            _kill_process_tree(pid)
        _active_processes.clear()
    else:
        logger.info("[SubprocessMgr] Shutting down — no active processes")

    if _job_handle is not None and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_job_handle)
            logger.info("[SubprocessMgr] Job Object handle closed")
        except Exception as e:
            logger.warning("[SubprocessMgr] Error closing Job Object: %s", e)
        _job_handle = None
