"""Tests for db/helpers.py"""

import json
from db.helpers import get_uid, now_iso, serialize_row, deserialize_row


class TestGetUid:
    def test_returns_string(self):
        assert isinstance(get_uid(), str)

    def test_length_8(self):
        assert len(get_uid()) == 8

    def test_unique(self):
        ids = {get_uid() for _ in range(100)}
        assert len(ids) == 100


class TestNowIso:
    def test_returns_iso_string(self):
        ts = now_iso()
        assert isinstance(ts, str)
        assert "T" in ts

    def test_contains_utc(self):
        ts = now_iso()
        # Should contain UTC offset info
        assert "+" in ts or "Z" in ts


class TestSerializeRow:
    def test_json_cols_serialized(self):
        data = {"id": "1", "steps": [{"name": "step1"}], "inputs": []}
        result = serialize_row("pipelines", data)
        assert isinstance(result["steps"], str)
        assert json.loads(result["steps"]) == [{"name": "step1"}]

    def test_non_json_cols_unchanged(self):
        data = {"id": "1", "name": "test"}
        result = serialize_row("pipelines", data)
        assert result["name"] == "test"

    def test_already_string_unchanged(self):
        data = {"id": "1", "steps": "[]"}
        result = serialize_row("pipelines", data)
        assert result["steps"] == "[]"

    def test_unknown_table_passthrough(self):
        data = {"id": "1", "foo": [1, 2]}
        result = serialize_row("unknown_table", data)
        assert result["foo"] == [1, 2]


class TestDeserializeRow:
    def test_json_cols_deserialized(self):
        data = {"id": "1", "steps": '[{"name": "step1"}]', "inputs": "[]"}
        result = deserialize_row("pipelines", data)
        assert isinstance(result["steps"], list)
        assert result["steps"][0]["name"] == "step1"

    def test_bool_cols_converted(self):
        data = {"id": "1", "is_enabled": 1}
        result = deserialize_row("tools", data)
        assert result["is_enabled"] is True

    def test_bool_false(self):
        data = {"id": "1", "is_enabled": 0}
        result = deserialize_row("tools", data)
        assert result["is_enabled"] is False

    def test_invalid_json_stays_string(self):
        data = {"id": "1", "steps": "not-json"}
        result = deserialize_row("pipelines", data)
        assert result["steps"] == "not-json"

    def test_round_trip(self):
        original = {"id": "1", "steps": [{"a": 1}], "inputs": [], "edges": [], "memories": []}
        serialized = serialize_row("pipelines", original)
        deserialized = deserialize_row("pipelines", serialized)
        assert deserialized["steps"] == [{"a": 1}]
        assert deserialized["inputs"] == []
