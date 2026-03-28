"""Tests for services/js_runner.py"""

import pytest
from services.js_runner import run_js


class TestRunJs:
    def test_basic_execution(self):
        code = "function process(input) { return input + ' world'; }"
        result = run_js(code, "hello")
        assert result == "hello world"

    def test_numeric_processing(self):
        code = "function process(a, b) { return a + b; }"
        result = run_js(code, 3, 4)
        assert result == 7

    def test_json_processing(self):
        code = """function process(input) {
            var obj = JSON.parse(input);
            return JSON.stringify({name: obj.name, upper: obj.name.toUpperCase()});
        }"""
        result = run_js(code, '{"name": "alice"}')
        import json
        parsed = json.loads(result)
        assert parsed["upper"] == "ALICE"

    def test_error_handling(self):
        code = "function process(input) { throw new Error('test error'); }"
        with pytest.raises(Exception):
            run_js(code, "hello")

    def test_array_return(self):
        code = "function process(input) { return [input]; }"
        result = run_js(code, "hello")
        assert result == ["hello"]
