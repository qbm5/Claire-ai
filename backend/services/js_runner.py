"""
JavaScript runner for pre/post-process functions in pipeline steps.
Uses py_mini_racer to execute JS code.
"""

from py_mini_racer import py_mini_racer


def run_js(js_code: str, *args):
    """Execute JS code and call its process() function with the given arguments."""
    ctx = py_mini_racer.MiniRacer()
    ctx.eval(js_code)
    result = ctx.call("process", *args)
    return result
