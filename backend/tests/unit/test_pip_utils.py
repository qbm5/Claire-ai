"""Tests for pip_utils."""

import pytest
from unittest.mock import patch, MagicMock

from services.pip_utils import is_package_installed, install_packages


class TestIsPackageInstalled:

    def test_installed_package(self):
        with patch("services.pip_utils.get_version", return_value="1.0.0"):
            assert is_package_installed("pytest") is True

    def test_not_installed(self):
        from importlib.metadata import PackageNotFoundError
        with patch("services.pip_utils.get_version", side_effect=PackageNotFoundError):
            assert is_package_installed("nonexistent-pkg") is False

    def test_handles_version_spec(self):
        with patch("services.pip_utils.get_version", return_value="2.0.0"):
            assert is_package_installed("numpy>=1.0") is True


class TestInstallPackages:

    def test_skips_already_installed(self):
        with patch("services.pip_utils.is_package_installed", return_value=True):
            results = install_packages(["already-installed"])
        assert len(results) == 0

    def test_installs_missing_package(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed test-pkg"

        with patch("services.pip_utils.is_package_installed", return_value=False), \
             patch("services.pip_utils.subprocess.run", return_value=mock_result):
            results = install_packages(["test-pkg"])

        assert len(results) == 1
        assert results[0]["package"] == "test-pkg"
        assert results[0]["success"] is True

    def test_handles_install_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error installing"

        with patch("services.pip_utils.is_package_installed", return_value=False), \
             patch("services.pip_utils.subprocess.run", return_value=mock_result):
            results = install_packages(["bad-pkg"])

        assert len(results) == 1
        assert results[0]["success"] is False

    def test_skips_empty_strings(self):
        with patch("services.pip_utils.is_package_installed", return_value=True):
            results = install_packages(["", "  ", "valid-pkg"])
        assert len(results) == 0
