"""
Subprocess wrapper for Custom triggers.

Launched by trigger_service._custom_loop as a separate process.
Imports the user's on_trigger.py, looks for run(emit), and calls it.
emit(data) writes JSON lines to stdout for the parent to consume.

Protocol (stdout, one JSON object per line):
  {"type":"emit","data":{...}}
  {"type":"log","level":"info","message":"..."}
"""

import asyncio
import importlib.util
import json
import os
import sys
import traceback


def _make_emit():
    """Return an emit() callable that writes JSON lines to stdout."""
    def emit(data: dict | None = None):
        if data is None:
            data = {}
        line = json.dumps({"type": "emit", "data": data}, default=str)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    return emit


def _log(level: str, message: str):
    line = json.dumps({"type": "log", "level": level, "message": message})
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"type": "log", "level": "error", "message": "No module path provided"}))
        sys.exit(1)

    module_path = sys.argv[1]

    if not os.path.isfile(module_path):
        _log("error", f"Module file not found: {module_path}")
        sys.exit(1)

    # Load the user module
    try:
        spec = importlib.util.spec_from_file_location("user_trigger", module_path)
        if spec is None or spec.loader is None:
            _log("error", f"Cannot load module: {module_path}")
            sys.exit(1)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception:
        _log("error", f"Failed to import module:\n{traceback.format_exc()}")
        sys.exit(1)

    fn = getattr(module, "run", None)
    if fn is None:
        _log("error", "No run(emit) function found in module")
        sys.exit(1)

    emit = _make_emit()
    _log("info", "Custom trigger subprocess started")

    try:
        result = fn(emit)
        # Support async run() functions
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    except Exception:
        _log("error", f"run() raised an exception:\n{traceback.format_exc()}")
        sys.exit(1)

    _log("info", "run() returned normally")


if __name__ == "__main__":
    main()
