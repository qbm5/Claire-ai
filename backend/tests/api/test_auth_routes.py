"""Tests for api/auth_routes.py"""

import pytest
import os

os.environ["AUTH_ENABLED"] = "true"


class TestAuthStatus:
    def test_status_returns_auth_info(self, test_client):
        resp = test_client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_enabled" in data
        assert "has_owner" in data
        assert "needs_setup" in data
        assert "oauth_providers" in data


class TestRegister:
    def test_register_first_user(self, in_memory_db):
        """Test registration when no users exist."""
        from fastapi.testclient import TestClient
        from main import app

        # Temporarily enable auth
        import config
        old_auth = config.AUTH_ENABLED
        config.AUTH_ENABLED = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/auth/register", json={
                "username": "owner",
                "email": "owner@test.com",
                "password": "password123",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            assert data["user"]["role"] == "owner"
        finally:
            config.AUTH_ENABLED = old_auth
            app.dependency_overrides.clear()

    def test_register_fails_when_users_exist(self, in_memory_db, admin_user):
        """Registration should fail when users already exist."""
        from fastapi.testclient import TestClient
        from main import app
        import config
        old_auth = config.AUTH_ENABLED
        config.AUTH_ENABLED = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/auth/register", json={
                "username": "second",
                "email": "second@test.com",
                "password": "password123",
            })
            assert resp.status_code == 400
        finally:
            config.AUTH_ENABLED = old_auth
            app.dependency_overrides.clear()


class TestLogin:
    def test_login_success(self, in_memory_db, admin_user):
        from fastapi.testclient import TestClient
        from main import app
        import config
        old_auth = config.AUTH_ENABLED
        config.AUTH_ENABLED = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/auth/login", json={
                "username": "admin",
                "password": "admin123",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
        finally:
            config.AUTH_ENABLED = old_auth
            app.dependency_overrides.clear()

    def test_login_wrong_password(self, in_memory_db, admin_user):
        from fastapi.testclient import TestClient
        from main import app
        import config
        old_auth = config.AUTH_ENABLED
        config.AUTH_ENABLED = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong",
            })
            assert resp.status_code == 401
        finally:
            config.AUTH_ENABLED = old_auth
            app.dependency_overrides.clear()

    def test_login_nonexistent_user(self, in_memory_db):
        from fastapi.testclient import TestClient
        from main import app
        import config
        old_auth = config.AUTH_ENABLED
        config.AUTH_ENABLED = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/auth/login", json={
                "username": "nonexistent",
                "password": "test",
            })
            assert resp.status_code == 401
        finally:
            config.AUTH_ENABLED = old_auth
            app.dependency_overrides.clear()


class TestMe:
    def test_me_returns_user_info(self, test_client, admin_user):
        resp = test_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "username" in data


class TestUserManagement:
    def test_list_users(self, test_client, admin_user):
        resp = test_client.get("/api/auth/users")
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)

    def test_create_user(self, test_client, admin_user):
        resp = test_client.post("/api/auth/users", json={
            "username": "newuser",
            "email": "new@test.com",
            "password": "password123",
            "role": "user",
        })
        assert resp.status_code == 200

    def test_toggle_user_active(self, test_client, admin_user, regular_user):
        resp = test_client.put(f"/api/auth/users/{regular_user['id']}/active", json={
            "is_active": False,
        })
        assert resp.status_code == 200


class TestPasswordChange:

    def test_change_own_password(self, test_client, admin_user):
        resp = test_client.put("/api/auth/me/password", json={
            "current_password": "admin123",
            "new_password": "newpassword456",
        })
        assert resp.status_code == 200

    def test_change_wrong_current_password(self, test_client, admin_user):
        resp = test_client.put("/api/auth/me/password", json={
            "current_password": "wrongpassword",
            "new_password": "newpassword456",
        })
        assert resp.status_code in (400, 401)


class TestPermissions:

    def test_get_role_permissions(self, test_client, in_memory_db):
        resp = test_client.get("/api/auth/permissions")
        assert resp.status_code == 200

    def test_get_role_permissions_returns_list(self, test_client, in_memory_db):
        resp = test_client.get("/api/auth/permissions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_user_permissions(self, test_client, admin_user, regular_user):
        resp = test_client.get(f"/api/auth/users/{regular_user['id']}/permissions")
        assert resp.status_code == 200

    def test_set_user_permissions(self, test_client, admin_user, regular_user):
        resp = test_client.post(f"/api/auth/users/{regular_user['id']}/permissions", json=[
            {"resource_type": "tools", "can_create": True, "can_edit": True, "can_delete": True},
        ])
        assert resp.status_code == 200

    def test_get_user_access(self, test_client, admin_user, regular_user):
        resp = test_client.get(f"/api/auth/users/{regular_user['id']}/access")
        assert resp.status_code == 200

    def test_set_user_access(self, test_client, admin_user, regular_user, sample_tool):
        resp = test_client.post(f"/api/auth/users/{regular_user['id']}/access", json={
            "resource_type": "tools",
            "resource_ids": [sample_tool["id"]],
        })
        assert resp.status_code == 200


class TestProfile:

    def test_update_profile(self, test_client, admin_user):
        resp = test_client.put("/api/auth/me/profile", json={
            "display_name": "New Display Name",
        })
        assert resp.status_code == 200
