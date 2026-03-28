import os
from fastapi import APIRouter
from dotenv import set_key
import config
from database import get_all, get_by_id, upsert, delete_by_id
from db.helpers import get_uid, now_iso
from models.enums import PropertyType
from config import clear_model_pricing_cache

router = APIRouter()

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

SETTING_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
                 "LOCAL_LLM_URL", "LOCAL_LLM_API_KEY", "GITHUB_TOKEN", "DEFAULT_MODEL",
                 "DB_TYPE", "MSSQL_CONNECTION_STRING", "POSTGRES_CONNECTION_STRING",
                 "COSMOS_ENDPOINT", "COSMOS_KEY", "COSMOS_DATABASE", "AUTH_ENABLED",
                 "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
                 "TOOL_SAFE_MODE", "COMMUNITY_URL",
                 "AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_CONTAINER"]


def _obfuscate(val: str) -> str:
    if val and len(val) > 8:
        return val[:4] + "*" * (len(val) - 4)
    return val


def _is_obfuscated(val: str) -> bool:
    return bool(val) and len(val) > 4 and val[4] == "*"


@router.get("")
async def get_settings():
    return {
        "ANTHROPIC_API_KEY": _obfuscate(config.ANTHROPIC_API_KEY),
        "OPENAI_API_KEY": _obfuscate(config.OPENAI_API_KEY),
        "GOOGLE_API_KEY": _obfuscate(config.GOOGLE_API_KEY),
        "XAI_API_KEY": _obfuscate(config.XAI_API_KEY),
        "LOCAL_LLM_URL": config.LOCAL_LLM_URL,
        "LOCAL_LLM_API_KEY": _obfuscate(config.LOCAL_LLM_API_KEY) if config.LOCAL_LLM_API_KEY != "local" else config.LOCAL_LLM_API_KEY,
        "GITHUB_TOKEN": _obfuscate(config.GITHUB_TOKEN),
        "DEFAULT_MODEL": config.DEFAULT_MODEL,
        "DB_TYPE": config.DB_TYPE,
        "MSSQL_CONNECTION_STRING": _obfuscate(config.MSSQL_CONNECTION_STRING),
        "POSTGRES_CONNECTION_STRING": _obfuscate(config.POSTGRES_CONNECTION_STRING),
        "COSMOS_ENDPOINT": config.COSMOS_ENDPOINT,
        "COSMOS_KEY": _obfuscate(config.COSMOS_KEY),
        "COSMOS_DATABASE": config.COSMOS_DATABASE,
        "AUTH_ENABLED": str(config.AUTH_ENABLED).lower(),
        "GOOGLE_CLIENT_ID": config.GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": _obfuscate(config.GOOGLE_CLIENT_SECRET),
        "MICROSOFT_CLIENT_ID": config.MICROSOFT_CLIENT_ID,
        "MICROSOFT_CLIENT_SECRET": _obfuscate(config.MICROSOFT_CLIENT_SECRET),
        "TOOL_SAFE_MODE": str(config.TOOL_SAFE_MODE).lower(),
        "COMMUNITY_URL": config.COMMUNITY_URL,
        "AZURE_STORAGE_CONNECTION_STRING": _obfuscate(config.AZURE_STORAGE_CONNECTION_STRING),
        "AZURE_STORAGE_CONTAINER": config.AZURE_STORAGE_CONTAINER,
        "models": config.get_all_models(),
    }


@router.post("")
async def save_settings(settings: dict):
    # Create .env file if it doesn't exist
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w") as f:
            f.write("")

    for key in SETTING_KEYS:
        val = settings.get(key)
        if val is not None and not _is_obfuscated(val):
            set_key(ENV_PATH, key, val)
            os.environ[key] = val

    # Reload config from environment
    config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    config.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    config.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    config.XAI_API_KEY = os.getenv("XAI_API_KEY", "")
    config.LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "")
    config.LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "local")
    config.GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    config.DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-opus-4-6")
    config.DB_TYPE = os.getenv("DB_TYPE", "sqlite")
    config.MSSQL_CONNECTION_STRING = os.getenv("MSSQL_CONNECTION_STRING", "")
    config.POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING", "")
    config.COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
    config.COSMOS_KEY = os.getenv("COSMOS_KEY", "")
    config.COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "sourcechat")
    config.AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
    config.TOOL_SAFE_MODE = os.getenv("TOOL_SAFE_MODE", "true").lower() == "true"
    config.GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    config.GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    config.MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
    config.MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    config.COMMUNITY_URL = os.getenv("COMMUNITY_URL", "")
    config.AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    config.AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "tool-images")

    # Clear cached model pricing data
    clear_model_pricing_cache()

    # Re-register LLM providers with updated keys
    from services.llm import re_register_providers
    re_register_providers()

    return {"response": "ok"}


@router.get("/custom")
async def get_custom_settings():
    """Return custom variables grouped by resource (tools and triggers), with DB values."""
    from services.custom_var_service import get_all_groups
    groups = get_all_groups()
    # Obfuscate PASSWORD-type values
    for group in groups:
        for v in group["variables"]:
            if v["type"] == PropertyType.PASSWORD and v["value"]:
                v["value"] = _obfuscate(v["value"])
    return groups


@router.post("/custom")
async def save_custom_settings(settings: list[dict]):
    """Save custom variable values to DB."""
    from db.helpers import now_iso
    for item in settings:
        resource_type = item.get("resource_type", "")
        resource_id = item.get("resource_id", "")
        name = item.get("name", "").strip()
        value = item.get("value", "")
        if not name or not resource_type or not resource_id:
            continue
        if _is_obfuscated(value):
            continue
        rows = get_all(
            "custom_variables",
            "resource_type = ? AND resource_id = ? AND name = ?",
            (resource_type, resource_id, name),
        )
        now = now_iso()
        if rows:
            upsert("custom_variables", {**rows[0], "value": value, "updated_at": now})
        else:
            # Create the row if it doesn't exist yet (env var added but tool not saved)
            upsert("custom_variables", {
                "id": get_uid(),
                "resource_type": resource_type,
                "resource_id": resource_id,
                "name": name,
                "value": value,
                "created_at": now,
                "updated_at": now,
            })
    return {"response": "ok"}


# ── Model CRUD ────────────────────────────────────────────────────


@router.get("/models")
async def get_models():
    return get_all("models", order_by="sort_order ASC, created_at ASC")


@router.post("/models")
async def create_model(data: dict):
    now = now_iso()
    data.setdefault("id", get_uid())
    data.setdefault("created_at", now)
    data["updated_at"] = now
    clear_model_pricing_cache()
    return upsert("models", data)


@router.put("/models/reorder")
async def reorder_models(data: dict):
    """Update sort_order for a list of model IDs. Expects {ids: [id1, id2, ...]}"""
    ids = data.get("ids", [])
    for idx, mid in enumerate(ids):
        existing = get_by_id("models", mid)
        if existing:
            upsert("models", {**existing, "sort_order": idx, "updated_at": now_iso()})
    return {"response": "ok"}


@router.put("/models/{model_id}")
async def update_model(model_id: str, data: dict):
    existing = get_by_id("models", model_id)
    if not existing:
        return {"error": "not found"}
    data["id"] = model_id
    data["updated_at"] = now_iso()
    clear_model_pricing_cache()
    return upsert("models", data)


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    delete_by_id("models", model_id)
    clear_model_pricing_cache()
    return {"response": "ok"}
