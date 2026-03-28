import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "local")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-opus-4-6")
DB_TYPE = os.getenv("DB_TYPE", "sqlite")
MSSQL_CONNECTION_STRING = os.getenv("MSSQL_CONNECTION_STRING", "")
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING", "")
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.getenv("COSMOS_KEY", "")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "sourcechat")
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "tool-images")


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "sourcechat.db")
INDEX_DIR = os.path.join(DATA_DIR, "indexes")
AGENTS_DIR = os.path.join(DATA_DIR, "agents")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
ARTIFACTS_DIR = os.path.join(DATA_DIR, "artifacts")
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
TRIGGERS_DIR = os.path.join(DATA_DIR, "triggers")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(INDEX_DIR, exist_ok=True)
os.makedirs(AGENTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(TRIGGERS_DIR, exist_ok=True)

CLAUDE_MODELS = [
    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "input_cost": 5.0, "output_cost": 25.0},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "input_cost": 3.0, "output_cost": 15.0},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude 4.5 Haiku", "input_cost": 1.00, "output_cost": 5.0},
]

OPENAI_MODELS = [
    {"id": "gpt-5.2", "name": "GPT-5.2", "input_cost": 1.75, "output_cost": 14.00},
    {"id": "gpt-5.1", "name": "GPT-5.1", "input_cost": 1.25, "output_cost": 10.00},
    {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex", "input_cost": 1.75, "output_cost": 14.00},
    {"id": "gpt-5-mini", "name": "GPT-5 Mini", "input_cost": 0.25, "output_cost": 2.00},
    {"id": "gpt-5-nano", "name": "GPT-5 Nano", "input_cost": 0.05, "output_cost": 0.40},
]

GEMINI_MODELS = [
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "input_cost": 1.25, "output_cost": 10.00},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "input_cost": 0.15, "output_cost": 0.60},
    {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite", "input_cost": 0.075, "output_cost": 0.30},
]

GROK_MODELS = [
    {"id": "grok-3", "name": "Grok 3", "input_cost": 3.00, "output_cost": 15.00},
    {"id": "grok-3-fast", "name": "Grok 3 Fast", "input_cost": 5.00, "output_cost": 25.00},
    {"id": "grok-3-mini", "name": "Grok 3 Mini", "input_cost": 0.30, "output_cost": 0.50},
    {"id": "grok-3-mini-fast", "name": "Grok 3 Mini Fast", "input_cost": 0.60, "output_cost": 4.00},
]

ALL_MODELS = CLAUDE_MODELS + OPENAI_MODELS + GEMINI_MODELS + GROK_MODELS

MILLION = 1_000_000

TOOL_RUNS_PIPELINE_ID = "__tool_runs__"

RESOURCE_TYPES = ["tools", "pipelines", "chatbots", "triggers"]

# Tool execution mode: True = sandbox filesystem, False = unrestricted
TOOL_SAFE_MODE = os.getenv("TOOL_SAFE_MODE", "true").lower() == "true"

# Community / support site URL for importing shared items
COMMUNITY_URL = os.getenv("COMMUNITY_URL", "")

# Subprocess safety limits
SUBPROCESS_TIMEOUT = int(os.getenv("SUBPROCESS_TIMEOUT", "600"))           # 10 min
SUBPROCESS_MAX_OUTPUT_FILE_MB = int(os.getenv("SUBPROCESS_MAX_FILE_MB", "2048"))  # 2 GB
AGENT_FUNCTION_TIMEOUT = int(os.getenv("AGENT_FUNCTION_TIMEOUT", "900"))   # 15 min

def get_all_models() -> list[dict]:
    from database import get_all
    rows = get_all("models", order_by="sort_order ASC, created_at ASC")
    return [{"id": r["model_id"], "name": r["name"], "provider": r.get("provider", "anthropic"),
             "input_cost": r["input_cost"], "output_cost": r["output_cost"]} for r in rows]


_model_pricing_cache: dict[str, dict] = {}


def clear_model_pricing_cache():
    """Clear the cached model pricing data (call after settings/models are saved)."""
    _model_pricing_cache.clear()


def get_model_pricing(model_id: str):
    if model_id in _model_pricing_cache:
        return _model_pricing_cache[model_id]
    from database import get_all
    rows = get_all("models", "model_id = ?", (model_id,))
    if rows:
        r = rows[0]
        result = {"id": r["model_id"], "name": r["name"], "input_cost": r["input_cost"],
                  "output_cost": r["output_cost"]}
    else:
        result = {"id": model_id, "name": model_id, "input_cost": 3.0, "output_cost": 15.0}
    _model_pricing_cache[model_id] = result
    return result
