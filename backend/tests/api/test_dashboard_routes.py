"""Tests for dashboard API routes."""

import pytest
import database
from models.enums import PipelineStatusType
from db.helpers import now_iso


class TestDashboardGet:

    def test_returns_dashboard_data(self, test_client, in_memory_db):
        resp = test_client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        # Dashboard returns a flat dict with keys like active_runs, etc.
        assert isinstance(data, dict)

    def test_with_pipeline_runs(self, test_client, in_memory_db, sample_pipeline):
        database.upsert("pipeline_runs", {
            "id": "run-1",
            "pipeline_id": sample_pipeline["id"],
            "pipeline_snapshot": sample_pipeline,
            "status": PipelineStatusType.Completed,
            "steps": [],
            "inputs": [],
            "outputs": [],
            "created_at": now_iso(),
            "completed_at": now_iso(),
            "user_id": "admin-id",
        })
        resp = test_client.get("/api/dashboard")
        assert resp.status_code == 200


class TestForceStop:

    def test_stop_pipeline_run(self, test_client, in_memory_db, sample_pipeline):
        database.upsert("pipeline_runs", {
            "id": "run-stop",
            "pipeline_id": sample_pipeline["id"],
            "pipeline_snapshot": sample_pipeline,
            "status": PipelineStatusType.Running,
            "steps": [],
            "inputs": [],
            "outputs": [],
            "created_at": now_iso(),
        })
        resp = test_client.post("/api/dashboard/runs/run-stop/stop")
        assert resp.status_code == 200

