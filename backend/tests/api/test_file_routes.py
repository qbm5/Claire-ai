"""Tests for file upload/download routes."""

import os
import pytest
from unittest.mock import patch


class TestFileUpload:

    def test_upload_file(self, test_client, in_memory_db, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "UPLOADS_DIR", str(tmp_path))

        resp = test_client.post(
            "/api/upload/target-1",
            files={"files": ("test.txt", b"file content", "text/plain")},
        )
        assert resp.status_code == 200

    def test_list_uploads(self, test_client, in_memory_db, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "UPLOADS_DIR", str(tmp_path))

        target_dir = tmp_path / "target-2"
        target_dir.mkdir()
        (target_dir / "file1.txt").write_text("content")

        resp = test_client.get("/api/uploads/target-2")
        assert resp.status_code == 200

    def test_delete_upload(self, test_client, in_memory_db, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "UPLOADS_DIR", str(tmp_path))

        target_dir = tmp_path / "target-3"
        target_dir.mkdir()
        (target_dir / "delete_me.txt").write_text("content")

        resp = test_client.delete("/api/uploads/target-3/delete_me.txt")
        assert resp.status_code == 200
