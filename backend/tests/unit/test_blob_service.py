"""Tests for services/blob_service.py — mock-based tests."""

from unittest.mock import patch, MagicMock
from services.blob_service import delete_blob


class TestDeleteBlob:
    @patch("services.blob_service._get_container_client")
    def test_delete_valid_url(self, mock_get_client):
        mock_container = MagicMock()
        mock_get_client.return_value = mock_container

        delete_blob("https://storage.blob.core.windows.net/images/abc123.jpg")
        mock_container.delete_blob.assert_called_once_with("abc123.jpg")

    @patch("services.blob_service._get_container_client")
    def test_delete_empty_url(self, mock_get_client):
        delete_blob("")
        mock_get_client.assert_not_called()

    @patch("services.blob_service._get_container_client")
    def test_delete_handles_exception(self, mock_get_client):
        mock_container = MagicMock()
        mock_container.delete_blob.side_effect = Exception("Not found")
        mock_get_client.return_value = mock_container

        # Should not raise
        delete_blob("https://storage.blob.core.windows.net/images/missing.jpg")
