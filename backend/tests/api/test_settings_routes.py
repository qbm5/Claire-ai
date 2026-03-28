"""Tests for settings API routes."""

import pytest
import database


class TestGetSettings:

    def test_returns_settings(self, test_client, in_memory_db):
        resp = test_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        # Settings returns a flat dict of config values, not {"response": ...}
        assert isinstance(data, dict)


class TestModelsCrud:

    def test_list_models(self, test_client, in_memory_db):
        resp = test_client.get("/api/settings/models")
        assert resp.status_code == 200

    def test_create_model(self, test_client, in_memory_db):
        resp = test_client.post("/api/settings/models", json={
            "model_id": "test-model",
            "name": "Test Model",
            "provider": "anthropic",
            "input_cost": 3.0,
            "output_cost": 15.0,
        })
        assert resp.status_code == 200

    def test_update_model(self, test_client, in_memory_db):
        database.upsert("models", {
            "id": "m1",
            "model_id": "test-model",
            "name": "Old Name",
            "provider": "anthropic",
            "input_cost": 3.0,
            "output_cost": 15.0,
            "sort_order": 0,
        })
        resp = test_client.put("/api/settings/models/m1", json={
            "name": "New Name",
        })
        assert resp.status_code == 200

    def test_delete_model(self, test_client, in_memory_db):
        database.upsert("models", {
            "id": "m2",
            "model_id": "delete-me",
            "name": "Delete Me",
            "provider": "test",
            "input_cost": 1.0,
            "output_cost": 1.0,
            "sort_order": 0,
        })
        resp = test_client.delete("/api/settings/models/m2")
        assert resp.status_code == 200

    def test_reorder_models(self, test_client, in_memory_db):
        for i in range(3):
            database.upsert("models", {
                "id": f"m{i}", "model_id": f"model-{i}", "name": f"M{i}",
                "provider": "test", "input_cost": 1, "output_cost": 1, "sort_order": i,
            })
        resp = test_client.put("/api/settings/models/reorder", json={
            "ids": ["m2", "m0", "m1"],
        })
        assert resp.status_code == 200


class TestSettingsPermissions:

    def test_regular_user_blocked(self, regular_user_client, in_memory_db):
        # Settings routes require admin
        resp = regular_user_client.get("/api/settings")
        assert resp.status_code == 403
