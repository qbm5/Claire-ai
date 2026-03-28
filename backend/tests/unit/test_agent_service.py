"""Tests for services/agent_service.py — pure function tests."""

import inspect
from services.agent_service import _python_type_to_json_type, _func_to_tool_schema


class TestPythonTypeToJsonType:
    def test_str(self):
        assert _python_type_to_json_type(str) == "string"

    def test_int(self):
        assert _python_type_to_json_type(int) == "integer"

    def test_float(self):
        assert _python_type_to_json_type(float) == "number"

    def test_bool(self):
        assert _python_type_to_json_type(bool) == "boolean"

    def test_list(self):
        assert _python_type_to_json_type(list) == "array"

    def test_empty_annotation(self):
        assert _python_type_to_json_type(inspect.Parameter.empty) == "string"

    def test_unknown_defaults_to_string(self):
        assert _python_type_to_json_type(dict) == "string"


class TestFuncToToolSchema:
    def test_simple_function(self):
        def hello(name: str) -> str:
            """Say hello to someone."""
            return f"Hello {name}"

        schema = _func_to_tool_schema(hello)
        assert schema["name"] == "hello"
        assert schema["description"] == "Say hello to someone."
        assert "name" in schema["input_schema"]["properties"]
        assert "name" in schema["input_schema"]["required"]

    def test_multiple_params(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        schema = _func_to_tool_schema(add)
        assert len(schema["input_schema"]["properties"]) == 2
        assert schema["input_schema"]["properties"]["a"]["type"] == "integer"
        assert schema["input_schema"]["properties"]["b"]["type"] == "integer"

    def test_optional_params(self):
        def greet(name: str, greeting: str = "Hello") -> str:
            """Greet someone."""
            return f"{greeting} {name}"

        schema = _func_to_tool_schema(greet)
        assert "name" in schema["input_schema"]["required"]
        assert "greeting" not in schema["input_schema"]["required"]

    def test_no_docstring(self):
        def mystery(x: str):
            return x

        schema = _func_to_tool_schema(mystery)
        assert schema["description"] == "mystery"

    def test_no_annotations(self):
        def plain(x):
            """Plain function."""
            return x

        schema = _func_to_tool_schema(plain)
        assert schema["input_schema"]["properties"]["x"]["type"] == "string"

    def test_mixed_types(self):
        def process(text: str, count: int, active: bool, rate: float):
            """Process data."""
            pass

        schema = _func_to_tool_schema(process)
        props = schema["input_schema"]["properties"]
        assert props["text"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["active"]["type"] == "boolean"
        assert props["rate"]["type"] == "number"

    def test_no_params(self):
        def noop():
            """Do nothing."""
            pass

        schema = _func_to_tool_schema(noop)
        assert schema["input_schema"]["properties"] == {}
        assert schema["input_schema"]["required"] == []
