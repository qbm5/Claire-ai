"""Tests for trigger API routes."""

import pytest
import database


class TestTriggerList:

    def test_list_triggers(self, test_client, sample_trigger):
        resp = test_client.get("/api/triggers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(t["id"] == "test-trigger-1" for t in data)

    def test_list_empty(self, test_client, in_memory_db):
        resp = test_client.get("/api/triggers")
        assert resp.status_code == 200


class TestTriggerGet:

    def test_get_existing(self, test_client, sample_trigger):
        resp = test_client.get("/api/triggers/test-trigger-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Trigger"

    def test_get_nonexistent(self, test_client, in_memory_db):
        resp = test_client.get("/api/triggers/nonexistent")
        assert resp.status_code == 200


class TestTriggerCreate:

    def test_create_trigger(self, test_client, in_memory_db):
        resp = test_client.post("/api/triggers", json={
            "name": "New Trigger",
            "trigger_type": "Cron",
            "cron_expression": "*/5 * * * *",
            "is_enabled": False,
        })
        assert resp.status_code == 200

    def test_update_trigger(self, test_client, sample_trigger):
        resp = test_client.post("/api/triggers", json={
            "id": "test-trigger-1",
            "name": "Updated Trigger",
            "trigger_type": "Cron",
            "cron_expression": "0 */2 * * *",
        })
        assert resp.status_code == 200


class TestTriggerDelete:

    def test_delete_trigger(self, test_client, sample_trigger):
        resp = test_client.delete("/api/triggers/test-trigger-1")
        assert resp.status_code == 200

    def test_delete_nonexistent(self, test_client, in_memory_db):
        resp = test_client.delete("/api/triggers/nonexistent")
        assert resp.status_code == 200


class TestTriggerActions:

    def test_fire_trigger(self, test_client, sample_trigger):
        from unittest.mock import AsyncMock, patch
        with patch("api.trigger_routes.fire_trigger", new_callable=AsyncMock,
                   return_value={"status": "fired", "outputs": {}, "pipelines": []}):
            resp = test_client.post(f"/api/triggers/{sample_trigger['id']}/fire")
            assert resp.status_code == 200

    def test_list_after_create(self, test_client, in_memory_db):
        """Create and list triggers to verify round-trip."""
        test_client.post("/api/triggers", json={
            "name": "RT Test", "trigger_type": "Cron", "cron_expression": "*/5 * * * *",
        })
        resp = test_client.get("/api/triggers")
        assert resp.status_code == 200
        data = resp.json()
        assert any(t["name"] == "RT Test" for t in data)


class TestTriggerPermissions:

    def test_regular_user_blocked_from_create(self, regular_user_client, in_memory_db):
        resp = regular_user_client.post("/api/triggers", json={
            "name": "Blocked",
            "trigger_type": "Cron",
        })
        assert resp.status_code == 403

    def test_regular_user_blocked_from_delete(self, regular_user_client, sample_trigger):
        resp = regular_user_client.delete("/api/triggers/test-trigger-1")
        assert resp.status_code == 403
