"""Tests for services/trigger_service.py — code save/load tests."""

import os
import pytest
from unittest.mock import patch


class TestSaveTriggerCode:
    @patch("services.trigger_service.TRIGGERS_DIR")
    def test_save_and_load(self, mock_dir, tmp_path):
        mock_dir_val = str(tmp_path / "triggers")
        with patch("services.trigger_service.TRIGGERS_DIR", mock_dir_val):
            from services.trigger_service import save_trigger_code, _trigger_dir

            save_trigger_code("MyTrigger", "t1", "def on_trigger(context):\n    return context\n")

            tdir = _trigger_dir("MyTrigger", "t1")
            code_path = os.path.join(tdir, "on_trigger.py")
            assert os.path.isfile(code_path)
            with open(code_path) as f:
                content = f.read()
            assert "def on_trigger" in content

    @patch("services.trigger_service.TRIGGERS_DIR")
    def test_empty_code_noop(self, mock_dir, tmp_path):
        with patch("services.trigger_service.TRIGGERS_DIR", str(tmp_path / "triggers")):
            from services.trigger_service import save_trigger_code
            save_trigger_code("Test", "t1", "")
            # No file should be created
            tdir = os.path.join(str(tmp_path / "triggers"), "Test_t1")
            assert not os.path.exists(tdir)

    @patch("services.trigger_service.TRIGGERS_DIR")
    def test_name_sanitization(self, mock_dir, tmp_path):
        with patch("services.trigger_service.TRIGGERS_DIR", str(tmp_path / "triggers")):
            from services.trigger_service import _trigger_dir
            tdir = _trigger_dir("My Trigger!@#", "t1")
            dirname = os.path.basename(tdir)
            assert " " not in dirname
            assert "!" not in dirname


class TestLoadTriggerFunction:
    @patch("services.trigger_service.TRIGGERS_DIR")
    def test_load_existing(self, mock_dir, tmp_path):
        with patch("services.trigger_service.TRIGGERS_DIR", str(tmp_path / "triggers")):
            with patch("services.custom_var_service.get_vars_for_resource", return_value={}):
                from services.trigger_service import save_trigger_code, load_trigger_function

                code = "def on_trigger(context):\n    return {'result': 'ok'}\n"
                save_trigger_code("Test", "t1", code)
                fn = load_trigger_function("Test", "t1")
                assert fn is not None
                assert callable(fn)
                result = fn({"trigger_name": "Test"})
                assert result == {"result": "ok"}

    @patch("services.trigger_service.TRIGGERS_DIR")
    def test_load_nonexistent(self, mock_dir, tmp_path):
        with patch("services.trigger_service.TRIGGERS_DIR", str(tmp_path / "triggers")):
            from services.trigger_service import load_trigger_function
            fn = load_trigger_function("NoSuch", "t999")
            assert fn is None
