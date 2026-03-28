"""Tests for oauth_service."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from services.oauth_service import (
    get_configured_providers,
    generate_state,
    validate_state,
    build_auth_url,
    exchange_code,
    get_user_info,
)


class TestGetConfiguredProviders:

    def test_returns_providers_with_credentials(self, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "gid")
        monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "gsecret")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_ID", "")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_SECRET", "")
        result = get_configured_providers()
        assert "google" in result
        assert "microsoft" not in result

    def test_returns_empty_when_none_configured(self, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "")
        monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_ID", "")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_SECRET", "")
        result = get_configured_providers()
        assert result == []


class TestStateManagement:

    def test_generate_returns_string(self):
        state = generate_state()
        assert isinstance(state, str)
        assert len(state) > 10

    def test_validate_fresh_state(self):
        state = generate_state()
        assert validate_state(state) is True

    def test_validate_unknown_state(self):
        assert validate_state("unknown-state") is False

    def test_validate_consumed_state(self):
        state = generate_state()
        assert validate_state(state) is True
        # Second validation should fail (consumed)
        assert validate_state(state) is False


class TestBuildAuthUrl:

    def test_google_url(self, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "google-id")
        monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "secret")
        url = build_auth_url("google", "http://localhost/callback")
        assert "accounts.google.com" in url
        assert "google-id" in url
        assert "redirect_uri" in url

    def test_microsoft_url(self, monkeypatch):
        monkeypatch.setattr("config.MICROSOFT_CLIENT_ID", "ms-id")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_SECRET", "secret")
        url = build_auth_url("microsoft", "http://localhost/callback")
        assert "microsoft" in url.lower() or "login" in url.lower()
        assert "ms-id" in url


class TestExchangeCode:

    @pytest.mark.asyncio
    async def test_posts_to_token_url(self, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "gid")
        monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "gsecret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "token123", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.oauth_service.httpx.AsyncClient", return_value=mock_client):
            result = await exchange_code("google", "auth-code", "http://localhost/callback")

        assert result["access_token"] == "token123"
        mock_client.post.assert_called_once()


class TestGetUserInfo:

    @pytest.mark.asyncio
    async def test_google_user_info(self, monkeypatch):
        monkeypatch.setattr("config.GOOGLE_CLIENT_ID", "gid")
        monkeypatch.setattr("config.GOOGLE_CLIENT_SECRET", "gs")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sub": "google-user-123",
            "email": "user@gmail.com",
            "name": "Test User",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.oauth_service.httpx.AsyncClient", return_value=mock_client):
            result = await get_user_info("google", "access-token")

        assert result["id"] == "google-user-123"
        assert result["email"] == "user@gmail.com"

    @pytest.mark.asyncio
    async def test_microsoft_user_info(self, monkeypatch):
        monkeypatch.setattr("config.MICROSOFT_CLIENT_ID", "mid")
        monkeypatch.setattr("config.MICROSOFT_CLIENT_SECRET", "ms")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "ms-user-456",
            "mail": "user@outlook.com",
            "displayName": "MS User",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.oauth_service.httpx.AsyncClient", return_value=mock_client):
            result = await get_user_info("microsoft", "access-token")

        assert result["id"] == "ms-user-456"
        assert result["email"] == "user@outlook.com"
