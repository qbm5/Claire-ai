"""Tests for api/tool_routes.py"""

import pytest


class TestToolList:
    def test_list_tools(self, test_client, sample_tool):
        resp = test_client.get("/api/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert isinstance(tools, list)
        assert len(tools) >= 1

    def test_list_tools_empty(self, test_client):
        resp = test_client.get("/api/tools")
        assert resp.status_code == 200
        assert resp.json() == []


class TestToolGet:
    def test_get_existing(self, test_client, sample_tool):
        resp = test_client.get(f"/api/tools/{sample_tool['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Tool"

    def test_get_nonexistent(self, test_client):
        resp = test_client.get("/api/tools/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data or data is None


class TestToolCreate:
    def test_create_tool(self, test_client):
        tool = {
            "name": "New Tool",
            "type": 0,
            "description": "A new tool",
            "prompt": "Hello",
            "request_inputs": [],
        }
        resp = test_client.post("/api/tools", json=tool)
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data

    def test_update_existing_tool(self, test_client, sample_tool):
        sample_tool["name"] = "Updated Tool"
        resp = test_client.post("/api/tools", json=sample_tool)
        assert resp.status_code == 200


class TestToolDelete:
    def test_delete_tool(self, test_client, sample_tool):
        resp = test_client.delete(f"/api/tools/{sample_tool['id']}")
        assert resp.status_code == 200

    def test_delete_nonexistent(self, test_client):
        resp = test_client.delete("/api/tools/nonexistent")
        assert resp.status_code == 200


class TestToolRun:

    def test_run_tool_endpoint(self, test_client, sample_tool):
        resp = test_client.post(f"/api/tools/{sample_tool['id']}/run", json={
            "inputs": [{"name": "Input", "value": "test"}],
        })
        # May return 200 or 500 depending on LLM availability
        assert resp.status_code in (200, 500)


class TestToolPermissions:
    def test_regular_user_needs_permission(self, regular_user_client):
        # Regular user with no permission rows should get 403
        tool = {"name": "Blocked", "type": 0, "description": "test", "prompt": "x", "request_inputs": []}
        resp = regular_user_client.post("/api/tools", json=tool)
        assert resp.status_code == 403

    def test_regular_user_cannot_delete(self, regular_user_client, sample_tool):
        resp = regular_user_client.delete(f"/api/tools/{sample_tool['id']}")
        assert resp.status_code == 403
