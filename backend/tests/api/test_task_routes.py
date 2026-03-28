"""Tests for task API routes."""

import pytest
import database


class TestTaskPlanList:

    def test_list_plans(self, test_client, sample_task_plan):
        resp = test_client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(p["id"] == "test-plan-1" for p in data)

    def test_list_empty(self, test_client, in_memory_db):
        resp = test_client.get("/api/tasks")
        assert resp.status_code == 200


class TestTaskPlanGet:

    def test_get_existing(self, test_client, sample_task_plan):
        resp = test_client.get("/api/tasks/test-plan-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Task Plan"

    def test_get_nonexistent(self, test_client, in_memory_db):
        resp = test_client.get("/api/tasks/nonexistent")
        assert resp.status_code == 200


class TestTaskPlanCreate:

    def test_create_plan(self, test_client, in_memory_db):
        resp = test_client.post("/api/tasks", json={
            "name": "New Plan",
            "request": "Do a thing",
            "model": "claude-sonnet-4-6",
        })
        assert resp.status_code == 200


class TestTaskPlanDelete:

    def test_delete_plan(self, test_client, sample_task_plan):
        resp = test_client.delete("/api/tasks/test-plan-1")
        assert resp.status_code == 200


class TestTaskRuns:

    def test_list_all_runs(self, test_client, in_memory_db):
        resp = test_client.get("/api/tasks/runs/all")
        assert resp.status_code == 200

    def test_list_runs_for_plan(self, test_client, sample_task_plan):
        resp = test_client.get("/api/tasks/test-plan-1/runs")
        assert resp.status_code == 200

    def test_delete_run(self, test_client, in_memory_db):
        database.upsert("task_runs", {
            "id": "run-1",
            "task_plan_id": "plan-1",
            "status": 2,
            "output": "done",
        })
        resp = test_client.delete("/api/tasks/runs/run-1")
        assert resp.status_code == 200

    def test_stop_run(self, test_client, in_memory_db):
        database.upsert("task_runs", {
            "id": "run-2",
            "task_plan_id": "plan-1",
            "status": 1,
        })
        resp = test_client.post("/api/tasks/runs/run-2/stop")
        assert resp.status_code == 200
