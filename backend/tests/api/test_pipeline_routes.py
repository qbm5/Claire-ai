"""Tests for api/pipeline_routes.py"""

import pytest


class TestPipelineList:
    def test_list_pipelines(self, test_client, sample_pipeline):
        resp = test_client.get("/api/pipelines")
        assert resp.status_code == 200
        pipelines = resp.json()
        assert isinstance(pipelines, list)
        # Should include our test pipeline (and possibly the system __tool_runs__ pipeline)
        ids = [p["id"] for p in pipelines]
        assert "test-pipeline-1" in ids

    def test_list_empty(self, test_client):
        resp = test_client.get("/api/pipelines")
        assert resp.status_code == 200


class TestPipelineGet:
    def test_get_existing(self, test_client, sample_pipeline):
        resp = test_client.get(f"/api/pipelines/{sample_pipeline['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Pipeline"

    def test_get_nonexistent(self, test_client):
        resp = test_client.get("/api/pipelines/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data or data is None


class TestPipelineCreate:
    def test_create_pipeline(self, test_client):
        pipeline = {
            "name": "New Pipeline",
            "description": "test",
            "steps": [],
            "inputs": [],
            "edges": [],
        }
        resp = test_client.post("/api/pipelines", json=pipeline)
        assert resp.status_code == 200
        assert "response" in resp.json()

    def test_update_pipeline(self, test_client, sample_pipeline):
        sample_pipeline["name"] = "Updated Pipeline"
        resp = test_client.post("/api/pipelines", json=sample_pipeline)
        assert resp.status_code == 200


class TestPipelineCopy:
    def test_copy_pipeline(self, test_client, sample_pipeline):
        resp = test_client.post(f"/api/pipelines/{sample_pipeline['id']}/copy", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        # The copy should have a new ID
        assert data["response"] != sample_pipeline["id"]


class TestPipelineDelete:
    def test_delete_pipeline(self, test_client, sample_pipeline):
        resp = test_client.delete(f"/api/pipelines/{sample_pipeline['id']}")
        assert resp.status_code == 200

    def test_delete_nonexistent(self, test_client):
        resp = test_client.delete("/api/pipelines/nonexistent")
        assert resp.status_code == 200


class TestPipelineRuns:
    def test_list_runs_empty(self, test_client, sample_pipeline):
        resp = test_client.get(f"/api/pipelines/{sample_pipeline['id']}/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_runs_with_data(self, test_client, sample_pipeline_run):
        import database
        run = sample_pipeline_run
        resp = test_client.get(f"/api/pipelines/{run['pipeline_id']}/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_get_run_detail(self, test_client, sample_pipeline_run):
        resp = test_client.get(f"/api/pipelines/runs/{sample_pipeline_run['id']}/detail")
        assert resp.status_code == 200

    def test_stop_pipeline_run(self, test_client, sample_pipeline_run):
        resp = test_client.post(f"/api/pipelines/runs/{sample_pipeline_run['id']}/stop")
        assert resp.status_code == 200


class TestPipelineRunActions:

    def test_resume_paused_pipeline(self, test_client, in_memory_db, sample_pipeline):
        import database
        from models.enums import PipelineStatusType
        from db.helpers import now_iso
        database.upsert("pipeline_runs", {
            "id": "paused-run",
            "pipeline_id": sample_pipeline["id"],
            "pipeline_snapshot": sample_pipeline,
            "steps": [],
            "inputs": [],
            "outputs": [],
            "status": PipelineStatusType.Paused,
            "created_at": now_iso(),
        })
        resp = test_client.post("/api/pipelines/runs/paused-run/resume")
        assert resp.status_code == 200

    def test_delete_pipeline_run(self, test_client, sample_pipeline_run):
        resp = test_client.delete(f"/api/pipelines/runs/{sample_pipeline_run['id']}")
        assert resp.status_code == 200

    def test_list_all_runs(self, test_client, sample_pipeline_run):
        """List runs for a specific pipeline."""
        resp = test_client.get(f"/api/pipelines/{sample_pipeline_run['pipeline_id']}/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestPipelinePermissions:
    def test_regular_user_cannot_create(self, regular_user_client):
        pipeline = {"name": "Blocked", "steps": [], "inputs": [], "edges": []}
        resp = regular_user_client.post("/api/pipelines", json=pipeline)
        assert resp.status_code == 403

    def test_regular_user_cannot_delete(self, regular_user_client, sample_pipeline):
        resp = regular_user_client.delete(f"/api/pipelines/{sample_pipeline['id']}")
        assert resp.status_code == 403
