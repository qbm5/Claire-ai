"""
Template engine - exact port of {{ variableName }} interpolation from V3.
Supports: {{ propName }}, {{ propName[5] }}, {{ propName[@] }}, {{ propName[-1] }}
"""

import re
import json


class Property:
    """Lightweight property for template resolution."""
    __slots__ = ("name", "value")

    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value


PATTERN = re.compile(r'\{\{(\s*[\w\d_\[\]@\.\- ]+\s*)\}\}')


def _resolve_dot_path(path: str, props_dict: dict):
    """Resolve 'StepName.field.nested' — split on first dot, JSON-parse base value, navigate."""
    parts = path.split('.', 1)
    base = parts[0]
    if base not in props_dict:
        return None
    if len(parts) == 1:
        return props_dict[base]
    try:
        obj = json.loads(str(props_dict[base]))
    except (json.JSONDecodeError, TypeError):
        return None
    for segment in parts[1].split('.'):
        if isinstance(obj, dict) and segment in obj:
            obj = obj[segment]
        else:
            return None
    return json.dumps(obj) if isinstance(obj, (dict, list)) else obj


def _parse_template(text: str, props: list, current_index: int | None = None,
                     escape_fn=None) -> str:
    """Internal: replace {{ variableName }} with values from props list.

    If escape_fn is provided, it is applied to each replacement value (e.g. for JSON escaping).
    Props can be list of Property objects or list of dicts with 'name'/'value' keys.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    props_dict = {}
    for prop in props:
        if isinstance(prop, dict):
            props_dict[prop["name"]] = prop.get("value", "")
        else:
            props_dict[prop.name] = prop.value

    def _finalize(val: str) -> str:
        return escape_fn(val) if escape_fn else val

    def replace_placeholder(match):
        placeholder = match.group(1).strip()

        index_match = re.match(r'([\w()]+)\[([@\-\d]+)\]', placeholder)
        if index_match and current_index is not None:
            base_name = index_match.group(1)
            index = index_match.group(2)
            if index == "@":
                index = 0
            else:
                index = int(index)
            new_index = index + current_index
            new_placeholder = f"{base_name}[{new_index}]"
            return _finalize(str(props_dict.get(new_placeholder, match.group(0))).strip())
        else:
            val = props_dict.get(placeholder)
            if val is None:
                val = _resolve_dot_path(placeholder, props_dict)
            if val is None:
                return _finalize(match.group(0))
            return _finalize(str(val).strip())

    return PATTERN.sub(replace_placeholder, text)


def parse_text(text: str, props: list, current_index: int | None = None) -> str:
    """Replace {{ variableName }} with values from props list."""
    return _parse_template(text, props, current_index)


def parse_json(text: str, props: list, current_index: int | None = None) -> str:
    """Same as parse_text but JSON-escapes replacement values."""
    return _parse_template(text, props, current_index, escape_fn=_make_json_safe)


def _make_json_safe(text: str) -> str:
    return json.dumps(text).strip('"')


def add_prop(props: list, name: str, value: str) -> list:
    """Add or update a property in the list."""
    for prop in props:
        if isinstance(prop, dict):
            if prop["name"] == name:
                prop["value"] = value
                return props
        else:
            if prop.name == name:
                prop.value = value
                return props
    props.append({"name": name, "value": value})
    return props
