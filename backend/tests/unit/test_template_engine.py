"""Tests for services/template_engine.py"""

from services.template_engine import parse_text, parse_json, add_prop, Property


class TestParseText:
    def test_simple_variable(self):
        props = [{"name": "Input", "value": "world"}]
        assert parse_text("Hello {{ Input }}", props) == "Hello world"

    def test_no_spaces_in_braces(self):
        props = [{"name": "Input", "value": "world"}]
        assert parse_text("Hello {{Input}}", props) == "Hello world"

    def test_multiple_variables(self):
        props = [{"name": "Name", "value": "Alice"}, {"name": "Age", "value": "30"}]
        assert parse_text("{{ Name }} is {{ Age }}", props) == "Alice is 30"

    def test_missing_variable_passthrough(self):
        props = [{"name": "Name", "value": "Alice"}]
        result = parse_text("{{ Name }} and {{ Missing }}", props)
        assert result == "Alice and {{ Missing }}"

    def test_property_objects(self):
        props = [Property("Input", "hello")]
        assert parse_text("Say {{ Input }}", props) == "Say hello"

    def test_empty_text(self):
        assert parse_text("", []) == ""

    def test_none_text(self):
        assert parse_text(None, []) == ""

    def test_non_string_text(self):
        assert parse_text(123, []) == "123"

    def test_array_index_at_symbol(self):
        props = [{"name": "Step[0]", "value": "first"}]
        result = parse_text("{{ Step[@] }}", props, current_index=0)
        assert result == "first"

    def test_array_negative_index(self):
        props = [{"name": "Step[2]", "value": "item2"}]
        result = parse_text("{{ Step[-1] }}", props, current_index=3)
        assert result == "item2"

    def test_array_positive_index(self):
        props = [{"name": "Step[5]", "value": "item5"}]
        result = parse_text("{{ Step[5] }}", props, current_index=0)
        assert result == "item5"

    def test_array_index_no_current_index_passthrough(self):
        props = [{"name": "Step[0]", "value": "first"}]
        # Without current_index, array notation uses dict lookup
        result = parse_text("{{ Step[@] }}", props, current_index=None)
        assert "Step[@]" in result

    def test_dot_path_resolution(self):
        import json
        props = [{"name": "Result", "value": json.dumps({"status": "ok", "data": {"count": 5}})}]
        assert parse_text("{{ Result.status }}", props) == "ok"

    def test_dot_path_nested(self):
        import json
        props = [{"name": "Result", "value": json.dumps({"data": {"count": 5}})}]
        assert parse_text("{{ Result.data.count }}", props) == "5"

    def test_dot_path_missing_returns_original(self):
        import json
        props = [{"name": "Result", "value": json.dumps({"status": "ok"})}]
        result = parse_text("{{ Result.missing }}", props)
        assert result == "{{ Result.missing }}"

    def test_dot_path_invalid_json_returns_none(self):
        props = [{"name": "Result", "value": "not json"}]
        result = parse_text("{{ Result.field }}", props)
        assert result == "{{ Result.field }}"

    def test_value_trimmed(self):
        props = [{"name": "Input", "value": "  hello  "}]
        assert parse_text("{{ Input }}", props) == "hello"

    def test_mixed_text_and_variables(self):
        props = [{"name": "Name", "value": "Bob"}]
        assert parse_text("Hello {{ Name }}, welcome!", props) == "Hello Bob, welcome!"


class TestParseJson:
    def test_simple_variable_json_safe(self):
        props = [{"name": "Input", "value": 'line1\nline2'}]
        result = parse_json("{{ Input }}", props)
        assert "\\n" in result

    def test_quotes_escaped(self):
        props = [{"name": "Input", "value": 'say "hello"'}]
        result = parse_json("{{ Input }}", props)
        assert '\\"' in result

    def test_missing_variable_passthrough_escaped(self):
        result = parse_json("{{ Missing }}", [])
        # Missing vars are passed through with JSON escaping applied
        assert "Missing" in result

    def test_backslash_escaped(self):
        props = [{"name": "Path", "value": "C:\\Users\\test"}]
        result = parse_json("{{ Path }}", props)
        assert "\\\\" in result


class TestAddProp:
    def test_add_new_prop_dict(self):
        props = [{"name": "A", "value": "1"}]
        result = add_prop(props, "B", "2")
        assert len(result) == 2
        assert result[-1] == {"name": "B", "value": "2"}

    def test_update_existing_prop_dict(self):
        props = [{"name": "A", "value": "1"}]
        result = add_prop(props, "A", "updated")
        assert len(result) == 1
        assert result[0]["value"] == "updated"

    def test_update_existing_prop_object(self):
        props = [Property("A", "1")]
        result = add_prop(props, "A", "updated")
        assert len(result) == 1
        assert result[0].value == "updated"

    def test_add_to_empty_list(self):
        result = add_prop([], "X", "42")
        assert len(result) == 1
        assert result[0]["name"] == "X"
