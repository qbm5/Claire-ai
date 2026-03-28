"""Tests for api/auth_deps.py"""

import pytest
from unittest.mock import patch, MagicMock
from api.auth_deps import (
    CurrentUser, OPEN_USER, check_permission, check_resource_access,
    get_accessible_resource_ids,
)


class TestCurrentUser:
    def test_admin_is_admin(self):
        u = CurrentUser("1", "admin", "admin")
        assert u.is_admin is True

    def test_owner_is_admin(self):
        u = CurrentUser("1", "owner", "owner")
        assert u.is_admin is True

    def test_user_not_admin(self):
        u = CurrentUser("1", "user", "user")
        assert u.is_admin is False

    def test_owner_is_owner(self):
        u = CurrentUser("1", "owner", "owner")
        assert u.is_owner is True

    def test_admin_not_owner(self):
        u = CurrentUser("1", "admin", "admin")
        assert u.is_owner is False

    def test_open_user_is_owner(self):
        assert OPEN_USER.is_owner is True
        assert OPEN_USER.is_admin is True


class TestCheckPermission:
    @patch("api.auth_deps.get_all")
    def test_admin_always_permitted(self, mock_get_all):
        admin = CurrentUser("1", "admin", "admin")
        assert check_permission(admin, "tools", "create") is True
        mock_get_all.assert_not_called()

    @patch("api.auth_deps.get_all")
    def test_owner_always_permitted(self, mock_get_all):
        owner = CurrentUser("1", "owner", "owner")
        assert check_permission(owner, "tools", "delete") is True

    @patch("api.auth_deps.get_all")
    def test_user_with_permission(self, mock_get_all):
        mock_get_all.return_value = [{"can_create": True, "can_edit": False, "can_delete": False}]
        user = CurrentUser("u1", "user", "user")
        assert check_permission(user, "tools", "create") is True

    @patch("api.auth_deps.get_all")
    def test_user_without_permission(self, mock_get_all):
        mock_get_all.return_value = [{"can_create": True, "can_edit": False, "can_delete": False}]
        user = CurrentUser("u1", "user", "user")
        assert check_permission(user, "tools", "delete") is False

    @patch("api.auth_deps.get_all")
    def test_no_permission_row_denies(self, mock_get_all):
        mock_get_all.return_value = []
        user = CurrentUser("u1", "user", "user")
        assert check_permission(user, "tools", "create") is False


class TestCheckResourceAccess:
    @patch("api.auth_deps.get_all")
    def test_admin_always_has_access(self, mock_get_all):
        admin = CurrentUser("1", "admin", "admin")
        assert check_resource_access(admin, "tools", "t1") is True

    @patch("api.auth_deps.get_all")
    def test_user_with_access(self, mock_get_all):
        mock_get_all.return_value = [{"resource_id": "t1"}]
        user = CurrentUser("u1", "user", "user")
        assert check_resource_access(user, "tools", "t1") is True

    @patch("api.auth_deps.get_all")
    def test_user_without_access(self, mock_get_all):
        mock_get_all.return_value = []
        user = CurrentUser("u1", "user", "user")
        assert check_resource_access(user, "tools", "t1") is False


class TestGetAccessibleResourceIds:
    @patch("api.auth_deps.get_all")
    def test_admin_returns_none(self, mock_get_all):
        admin = CurrentUser("1", "admin", "admin")
        assert get_accessible_resource_ids(admin, "tools") is None

    @patch("api.auth_deps.get_all")
    def test_user_returns_set(self, mock_get_all):
        mock_get_all.return_value = [
            {"resource_id": "t1"},
            {"resource_id": "t2"},
        ]
        user = CurrentUser("u1", "user", "user")
        result = get_accessible_resource_ids(user, "tools")
        assert result == {"t1", "t2"}

    @patch("api.auth_deps.get_all")
    def test_user_empty_access(self, mock_get_all):
        mock_get_all.return_value = []
        user = CurrentUser("u1", "user", "user")
        result = get_accessible_resource_ids(user, "tools")
        assert result == set()
