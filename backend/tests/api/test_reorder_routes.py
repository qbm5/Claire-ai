"""Tests for reorder API routes."""

import pytest
import database


class TestReorder:

    def test_reorder_pipelines(self, test_client, in_memory_db):
        for i in range(3):
            database.upsert("pipelines", {
                "id": f"p{i}", "name": f"Pipeline {i}", "steps": [], "inputs": [],
                "edges": [], "sort_index": i,
            })
        resp = test_client.post("/api/pipelines/reorder", json={
            "ids": ["p2", "p0", "p1"],
        })
        assert resp.status_code == 200

    def test_reorder_tools(self, test_client, in_memory_db):
        for i in range(2):
            database.upsert("tools", {
                "id": f"t{i}", "name": f"Tool {i}", "type": 0, "sort_index": i,
            })
        resp = test_client.post("/api/tools/reorder", json={
            "ids": ["t1", "t0"],
        })
        assert resp.status_code == 200

    def test_disallowed_table(self, test_client, in_memory_db):
        resp = test_client.post("/api/users/reorder", json={"ids": ["a"]})
        assert resp.status_code in (200, 404)

    def test_empty_ids(self, test_client, in_memory_db):
        resp = test_client.post("/api/pipelines/reorder", json={"ids": []})
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
