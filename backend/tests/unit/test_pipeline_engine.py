"""Tests for services/pipeline_engine.py — pure function tests."""

from services.pipeline_engine import _build_json_schema, _kv_to_dict


class TestBuildJsonSchema:
    def test_simple_string_field(self):
        fields = [{"key": "name", "type": "string"}]
        result = _build_json_schema(fields)
        assert result == {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

    def test_number_field(self):
        fields = [{"key": "count", "type": "number"}]
        result = _build_json_schema(fields)
        assert result["properties"]["count"]["type"] == "number"

    def test_boolean_field(self):
        fields = [{"key": "active", "type": "boolean"}]
        result = _build_json_schema(fields)
        assert result["properties"]["active"]["type"] == "boolean"

    def test_nested_object(self):
        fields = [
            {"key": "data", "type": "object", "children": [
                {"key": "name", "type": "string"},
                {"key": "age", "type": "number"},
            ]}
        ]
        result = _build_json_schema(fields)
        assert result["properties"]["data"]["type"] == "object"
        assert "name" in result["properties"]["data"]["properties"]

    def test_empty_key_skipped(self):
        fields = [{"key": "", "type": "string"}, {"key": "valid", "type": "string"}]
        result = _build_json_schema(fields)
        assert len(result["properties"]) == 1
        assert "valid" in result["properties"]

    def test_multiple_fields(self):
        fields = [
            {"key": "name", "type": "string"},
            {"key": "count", "type": "number"},
            {"key": "active", "type": "boolean"},
        ]
        result = _build_json_schema(fields)
        assert len(result["properties"]) == 3
        assert result["required"] == ["name", "count", "active"]

    def test_empty_fields(self):
        result = _build_json_schema([])
        assert result == {"type": "object", "properties": {}, "required": []}


class TestKvToDict:
    def test_kv_list(self):
        raw = [{"key": "Content-Type", "value": "application/json"}]
        result = _kv_to_dict(raw)
        assert result == {"Content-Type": "application/json"}

    def test_empty_list(self):
        assert _kv_to_dict([]) == {}

    def test_legacy_json_string_dict(self):
        import json
        raw = json.dumps({"Accept": "text/html"})
        result = _kv_to_dict(raw)
        assert result == {"Accept": "text/html"}

    def test_legacy_json_string_kv_array(self):
        import json
        raw = json.dumps([{"key": "X-Auth", "value": "token123"}])
        result = _kv_to_dict(raw)
        assert result == {"X-Auth": "token123"}

    def test_empty_string(self):
        assert _kv_to_dict("") == {}

    def test_none_passthrough(self):
        assert _kv_to_dict(None) == {}

    def test_invalid_json_string(self):
        assert _kv_to_dict("not json") == {}

    def test_skips_pairs_without_key(self):
        raw = [{"key": "", "value": "orphan"}, {"key": "valid", "value": "ok"}]
        result = _kv_to_dict(raw)
        assert result == {"valid": "ok"}

    def test_with_template_resolution(self):
        props = [{"name": "Token", "value": "abc123"}]
        raw = [{"key": "Authorization", "value": "Bearer {{ Token }}"}]
        result = _kv_to_dict(raw, props_chain=[props])
        assert result == {"Authorization": "Bearer abc123"}

    def test_nested_template_resolution(self):
        props1 = [{"name": "Host", "value": "example.com"}]
        props2 = [{"name": "Path", "value": "/api"}]
        raw = [{"key": "url", "value": "{{ Host }}{{ Path }}"}]
        result = _kv_to_dict(raw, props_chain=[props1, props2])
        assert result == {"url": "example.com/api"}
