"""Tests for rag_service."""

import os
import json
import pytest
import numpy as np
from unittest.mock import patch, MagicMock


class TestChunkText:

    def test_short_text_single_chunk(self):
        from services.rag_service import chunk_text
        result = chunk_text("Short text", chunk_size=512)
        assert len(result) == 1
        assert result[0] == "Short text"

    def test_long_text_splits_with_overlap(self):
        from services.rag_service import chunk_text
        text = "A" * 100
        result = chunk_text(text, chunk_size=30, overlap=10)
        assert len(result) > 1
        # Each chunk should be <= chunk_size
        for chunk in result:
            assert len(chunk) <= 30

    def test_empty_text(self):
        from services.rag_service import chunk_text
        result = chunk_text("")
        assert result == [""] or result == []


class TestBuildIndex:

    def test_builds_and_queries_index(self, tmp_path, monkeypatch):
        from services.rag_service import build_index, query_index

        monkeypatch.setattr("services.rag_service.INDEX_DIR", str(tmp_path))

        mock_model = MagicMock()
        # Return 1024-dim embeddings
        mock_model.encode.return_value = np.random.rand(1, 1024).astype(np.float32)

        with patch("services.rag_service._get_model", return_value=mock_model), \
             patch("services.rag_service.broadcast"):
            count = build_index("bot-1", [
                {"text": "Hello world", "source": "doc1.txt"},
                {"text": "Goodbye world", "source": "doc2.txt"},
            ])

        assert count > 0
        assert (tmp_path / "bot-1" / "index.faiss").exists()
        assert (tmp_path / "bot-1" / "metadata.json").exists()

    def test_empty_documents(self, tmp_path, monkeypatch):
        from services.rag_service import build_index
        monkeypatch.setattr("services.rag_service.INDEX_DIR", str(tmp_path))
        with patch("services.rag_service.broadcast"):
            count = build_index("bot-2", [])
        assert count == 0


class TestQueryIndex:

    def test_returns_empty_for_missing_index(self, tmp_path, monkeypatch):
        from services.rag_service import query_index
        monkeypatch.setattr("services.rag_service.INDEX_DIR", str(tmp_path))
        result = query_index("nonexistent", "test query")
        assert result == []


class TestDeleteIndex:

    def test_removes_index_directory(self, tmp_path, monkeypatch):
        from services.rag_service import delete_index
        monkeypatch.setattr("services.rag_service.INDEX_DIR", str(tmp_path))

        index_dir = tmp_path / "bot-del"
        index_dir.mkdir()
        (index_dir / "index.faiss").write_text("fake")

        delete_index("bot-del")
        assert not index_dir.exists()

    def test_delete_nonexistent_no_error(self, tmp_path, monkeypatch):
        from services.rag_service import delete_index
        monkeypatch.setattr("services.rag_service.INDEX_DIR", str(tmp_path))
        delete_index("nonexistent")  # Should not raise
