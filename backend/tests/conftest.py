"""Shared test fixtures for backend tests."""

import os
import sys

# Ensure backend directory is on sys.path so imports work
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Set env vars before any config imports
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("DB_TYPE", "sqlite")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("AUTH_ENABLED", "true")

import pytest
from db.providers.sqlite_provider import SQLiteProvider
from db.helpers import get_uid, now_iso
import database


@pytest.fixture()
def in_memory_db(tmp_path):
    """Create a fresh SQLite in-memory provider and monkey-patch database._provider."""
    db_path = str(tmp_path / "test.db")
    provider = SQLiteProvider(db_path)
    provider.init_db()

    old_provider = database._provider
    database._provider = provider
    yield provider
    database._provider = old_provider


@pytest.fixture()
def test_client(in_memory_db):
    """FastAPI TestClient with admin auth override."""
    from fastapi.testclient import TestClient
    from main import app
    from api.auth_deps import get_current_user, CurrentUser

    admin = CurrentUser("admin-id", "admin", "admin", display_name="Admin")
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def regular_user_client(in_memory_db):
    """FastAPI TestClient with non-admin auth."""
    from fastapi.testclient import TestClient
    from main import app
    from api.auth_deps import get_current_user, CurrentUser

    user = CurrentUser("user-id", "testuser", "user", display_name="Test User")
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_tool(in_memory_db):
    """Pre-inserted test tool."""
    tool_data = {
        "id": "test-tool-1",
        "name": "Test Tool",
        "type": 0,
        "tag": "test",
        "is_enabled": True,
        "description": "A test tool",
        "prompt": "Hello {{ Input }}",
        "system_prompt": "You are helpful.",
        "model": "claude-sonnet-4-6",
        "request_inputs": [{"name": "Input", "value": "", "is_required": True, "locked": True, "type": 0, "is_default": True}],
    }
    return database.upsert("tools", tool_data)


@pytest.fixture()
def sample_pipeline(in_memory_db):
    """Pre-inserted test pipeline."""
    pipeline_data = {
        "id": "test-pipeline-1",
        "name": "Test Pipeline",
        "description": "A test pipeline",
        "tag": "test",
        "steps": [],
        "inputs": [{"name": "Start", "value": ""}],
        "edges": [],
    }
    return database.upsert("pipelines", pipeline_data)


@pytest.fixture()
def sample_chatbot(in_memory_db):
    """Pre-inserted test chatbot."""
    chatbot_data = {
        "id": "test-chatbot-1",
        "name": "Test Chatbot",
        "description": "A test chatbot",
        "is_enabled": True,
        "is_deleted": False,
        "source_type": "text",
        "source_texts": ["Hello world"],
    }
    return database.upsert("chatbots", chatbot_data)


@pytest.fixture()
def admin_user(in_memory_db):
    """Pre-inserted admin user with hashed password."""
    from services.auth_service import hash_password
    user_data = {
        "id": "admin-id",
        "username": "admin",
        "email": "admin@test.com",
        "password_hash": hash_password("admin123"),
        "role": "admin",
        "is_active": True,
    }
    return database.upsert("users", user_data)


@pytest.fixture()
def regular_user(in_memory_db):
    """Pre-inserted regular user with hashed password."""
    from services.auth_service import hash_password
    user_data = {
        "id": "user-id",
        "username": "testuser",
        "email": "user@test.com",
        "password_hash": hash_password("user1234"),
        "role": "user",
        "is_active": True,
    }
    return database.upsert("users", user_data)


@pytest.fixture()
def sample_trigger(in_memory_db):
    """Pre-inserted test trigger."""
    trigger_data = {
        "id": "test-trigger-1",
        "name": "Test Trigger",
        "trigger_type": "Cron",
        "cron_expression": "0 * * * *",
        "is_enabled": True,
        "code": "def on_trigger(context):\n    return {'result': 'ok'}",
        "connections": [],
        "env_variables": [],
    }
    return database.upsert("triggers", trigger_data)


@pytest.fixture()
def sample_task_plan(in_memory_db):
    """Pre-inserted test task plan."""
    plan_data = {
        "id": "test-plan-1",
        "name": "Test Task Plan",
        "request": "Do something useful",
        "plan": [],
        "model": "claude-sonnet-4-6",
    }
    return database.upsert("task_plans", plan_data)


@pytest.fixture()
def sample_pipeline_run(in_memory_db, sample_pipeline):
    """Pre-inserted test pipeline run."""
    from models.enums import PipelineStatusType
    run_data = {
        "id": "test-run-1",
        "pipeline_id": sample_pipeline["id"],
        "pipeline_snapshot": sample_pipeline,
        "steps": [],
        "inputs": [{"name": "Start", "value": "hello"}],
        "outputs": [],
        "status": PipelineStatusType.Running,
        "current_step": 0,
        "created_at": now_iso(),
    }
    return database.upsert("pipeline_runs", run_data)


@pytest.fixture()
def temp_data_dir(tmp_path, monkeypatch):
    """Patch all data directories to use tmp_path subdirectories."""
    import config
    dirs = {
        "AGENTS_DIR": "agents",
        "TRIGGERS_DIR": "triggers",
        "UPLOADS_DIR": "uploads",
        "ARTIFACTS_DIR": "artifacts",
        "MEMORY_DIR": "memory",
        "INDEX_DIR": "index",
    }
    paths = {}
    for attr, subdir in dirs.items():
        if hasattr(config, attr):
            p = str(tmp_path / subdir)
            os.makedirs(p, exist_ok=True)
            monkeypatch.setattr(config, attr, p)
            paths[attr] = p
    return paths
