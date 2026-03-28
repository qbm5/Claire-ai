"""Tests for custom_var_service."""

import pytest
import database

from services.custom_var_service import (
    get_vars_for_resource,
    sync_var_schema,
    delete_vars_for_resource,
)


class TestGetVarsForResource:

    def test_returns_name_value_dict(self, in_memory_db):
        database.upsert("custom_variables", {
            "id": "cv-1", "resource_type": "tool", "resource_id": "t1",
            "name": "API_KEY", "value": "secret123",
        })
        database.upsert("custom_variables", {
            "id": "cv-2", "resource_type": "tool", "resource_id": "t1",
            "name": "BASE_URL", "value": "https://api.example.com",
        })
        result = get_vars_for_resource("tool", "t1")
        assert result == {"API_KEY": "secret123", "BASE_URL": "https://api.example.com"}

    def test_returns_empty_when_no_vars(self, in_memory_db):
        result = get_vars_for_resource("tool", "nonexistent")
        assert result == {}

    def test_filters_by_resource(self, in_memory_db):
        database.upsert("custom_variables", {
            "id": "cv-1", "resource_type": "tool", "resource_id": "t1",
            "name": "KEY1", "value": "val1",
        })
        database.upsert("custom_variables", {
            "id": "cv-2", "resource_type": "tool", "resource_id": "t2",
            "name": "KEY2", "value": "val2",
        })
        result = get_vars_for_resource("tool", "t1")
        assert result == {"KEY1": "val1"}


class TestSyncVarSchema:

    def test_creates_new_vars(self, in_memory_db):
        env_vars = [
            {"name": "API_KEY", "value": ""},
            {"name": "SECRET", "value": ""},
        ]
        sync_var_schema("tool", "t1", env_vars)

        result = get_vars_for_resource("tool", "t1")
        assert "API_KEY" in result
        assert "SECRET" in result

    def test_preserves_existing_values(self, in_memory_db):
        database.upsert("custom_variables", {
            "id": "cv-1", "resource_type": "tool", "resource_id": "t1",
            "name": "EXISTING", "value": "keep_this",
        })
        env_vars = [{"name": "EXISTING", "value": ""}]
        sync_var_schema("tool", "t1", env_vars)

        result = get_vars_for_resource("tool", "t1")
        assert result["EXISTING"] == "keep_this"

    def test_removes_unlisted_vars(self, in_memory_db):
        database.upsert("custom_variables", {
            "id": "cv-old", "resource_type": "tool", "resource_id": "t1",
            "name": "OLD_VAR", "value": "remove_me",
        })
        env_vars = [{"name": "NEW_VAR", "value": ""}]
        sync_var_schema("tool", "t1", env_vars)

        result = get_vars_for_resource("tool", "t1")
        assert "OLD_VAR" not in result
        assert "NEW_VAR" in result


class TestDeleteVarsForResource:

    def test_deletes_all_vars(self, in_memory_db):
        database.upsert("custom_variables", {
            "id": "cv-1", "resource_type": "tool", "resource_id": "t1",
            "name": "KEY1", "value": "val1",
        })
        database.upsert("custom_variables", {
            "id": "cv-2", "resource_type": "tool", "resource_id": "t1",
            "name": "KEY2", "value": "val2",
        })
        delete_vars_for_resource("tool", "t1")
        result = get_vars_for_resource("tool", "t1")
        assert result == {}

    def test_no_error_when_no_vars(self, in_memory_db):
        delete_vars_for_resource("tool", "nonexistent")
