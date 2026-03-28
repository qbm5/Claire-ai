"""Tests for artifact_service."""

import os
import pytest
from unittest.mock import patch

from services.artifact_service import (
    init_artifact_context,
    collect_artifacts,
    save_artifact,
    save_link,
    get_artifact_path,
)


@pytest.fixture()
def artifact_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("services.artifact_service.ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


class TestArtifactContext:

    def test_init_and_collect(self, artifact_dir):
        init_artifact_context("run-1")
        artifacts = collect_artifacts()
        assert artifacts == []

    def test_collect_returns_and_clears(self, artifact_dir):
        init_artifact_context("run-1")
        # Save a file to create an artifact
        src = artifact_dir / "source.txt"
        src.write_text("content")
        save_artifact(str(src), "test.txt")

        artifacts = collect_artifacts()
        assert len(artifacts) == 1
        # Second collect should be empty
        artifacts2 = collect_artifacts()
        assert artifacts2 == []


class TestSaveArtifact:

    def test_saves_file(self, artifact_dir):
        init_artifact_context("run-2")
        src = artifact_dir / "input.png"
        src.write_bytes(b"\x89PNG fake data")
        url = save_artifact(str(src), "output.png")
        assert "output.png" in url

        # File should be copied to artifacts dir
        dest = artifact_dir / "run-2" / "output.png"
        assert dest.exists()

    def test_auto_names_from_path(self, artifact_dir):
        init_artifact_context("run-3")
        src = artifact_dir / "myfile.pdf"
        src.write_text("pdf content")
        url = save_artifact(str(src))
        assert "myfile.pdf" in url

    def test_deduplicates_filename(self, artifact_dir):
        init_artifact_context("run-4")
        # Create two source files
        src1 = artifact_dir / "file.txt"
        src1.write_text("v1")
        src2 = artifact_dir / "file2.txt"
        src2.write_text("v2")

        save_artifact(str(src1), "output.txt")
        save_artifact(str(src2), "output.txt")  # Duplicate name

        run_dir = artifact_dir / "run-4"
        files = list(run_dir.iterdir())
        assert len(files) == 2

    def test_nonexistent_file_raises(self, artifact_dir):
        init_artifact_context("run-5")
        with pytest.raises(FileNotFoundError):
            save_artifact("/nonexistent/file.txt")


class TestSaveLink:

    def test_saves_link_artifact(self, artifact_dir):
        init_artifact_context("run-6")
        url = save_link("https://example.com", "Example", "A test link")
        assert url == "https://example.com"

        artifacts = collect_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0]["type"] == "link"
        assert artifacts[0]["url"] == "https://example.com"


class TestGetArtifactPath:

    def test_returns_path_for_existing(self, artifact_dir):
        run_dir = artifact_dir / "run-7"
        run_dir.mkdir()
        (run_dir / "test.txt").write_text("content")

        path = get_artifact_path("run-7", "test.txt")
        assert path is not None
        assert "test.txt" in path

    def test_returns_none_for_missing(self, artifact_dir):
        path = get_artifact_path("nonexistent", "file.txt")
        assert path is None
