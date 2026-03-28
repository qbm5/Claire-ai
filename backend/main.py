import os
import atexit
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Depends, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Silence verbose Azure SDK HTTP logging
logging.getLogger("azure").setLevel(logging.WARNING)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from database import init_db, get_by_id, get_all, upsert, count
from db.helpers import get_uid, now_iso
from event_bus import subscribe
from api.tool_routes import router as tool_router, ws_tool_test, ws_ai_assist
from api.chatbot_routes import router as chatbot_router, ws_chat
from api.pipeline_routes import router as pipeline_router, ws_ai_assist_pipeline
from api.settings_routes import router as settings_router
from api.file_routes import router as file_router
from api.trigger_routes import router as trigger_router, ws_ai_assist_trigger
from api.reorder_routes import router as reorder_router
from api.dashboard_routes import router as dashboard_router
from api.task_routes import router as task_router, ws_task_execute
from api.artifact_routes import router as artifact_router
from api.auth_routes import router as auth_router
from api.community_routes import router as community_router
from api.auth_deps import get_current_user, require_admin
from services.trigger_service import start_all_schedulers
from services.lsp_service import ws_lsp
from services.subprocess_manager import init_job_object, shutdown as subprocess_shutdown, set_on_change as set_proc_on_change
from services.auth_service import ensure_jwt_secret
import config
from config import TOOL_RUNS_PIPELINE_ID, RESOURCE_TYPES

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_jwt_secret()
    if not get_by_id("pipelines", TOOL_RUNS_PIPELINE_ID):
        upsert("pipelines", {
            "id": TOOL_RUNS_PIPELINE_ID,
            "name": "[System] Tool Runs",
            "steps": [],
            "inputs": [],
            "edges": [],
        })
    # Seed default role permissions if empty
    if count("role_permissions") == 0:
        now = now_iso()
        for rt in RESOURCE_TYPES:
            upsert("role_permissions", {
                "id": get_uid(),
                "resource_type": rt,
                "can_create": True,
                "can_edit": True,
                "can_delete": True,
                "can_use": True,
                "created_at": now,
                "updated_at": now,
            })

    # Migrate existing regular users: seed per-user permissions if missing
    from api.auth_routes import _seed_user_permissions, _seed_user_resource_access
    all_users = get_all("users")
    for u in all_users:
        if u["role"] in ("admin", "owner"):
            continue
        existing_perms = get_all("user_permissions", "user_id = ?", (u["id"],))
        if not existing_perms:
            _seed_user_permissions(u["id"], grant_all=True)
            _seed_user_resource_access(u["id"])

    # Seed default models if table is empty
    if count("models") == 0:
        now = now_iso()
        for m in config.CLAUDE_MODELS:
            upsert("models", {
                "id": get_uid(), "model_id": m["id"], "name": m["name"],
                "provider": "anthropic", "input_cost": m["input_cost"],
                "output_cost": m["output_cost"], "created_at": now, "updated_at": now,
            })
        for m in config.OPENAI_MODELS:
            upsert("models", {
                "id": get_uid(), "model_id": m["id"], "name": m["name"],
                "provider": "openai", "input_cost": m["input_cost"],
                "output_cost": m["output_cost"], "created_at": now, "updated_at": now,
            })

    # One-time migration: move existing .env custom variable values to DB
    if count("custom_variables") == 0:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
        from services.custom_var_service import sync_var_schema
        for resource_type, table in [("tool", "tools"), ("trigger", "triggers")]:
            for item in get_all(table):
                env_vars = item.get("env_variables", [])
                if not env_vars:
                    continue
                sync_var_schema(resource_type, item["id"], env_vars)
                for var in env_vars:
                    vname = var.get("name", "").strip()
                    if not vname:
                        continue
                    val = os.getenv(vname, "")
                    if val:
                        rows = get_all("custom_variables",
                            "resource_type = ? AND resource_id = ? AND name = ?",
                            (resource_type, item["id"], vname))
                        if rows:
                            upsert("custom_variables", {**rows[0], "value": val, "updated_at": now_iso()})

    init_job_object()
    atexit.register(subprocess_shutdown)

    # Broadcast SSE event when subprocess list changes (thread-safe)
    import asyncio
    loop = asyncio.get_running_loop()
    from event_bus import broadcast
    set_proc_on_change(lambda: loop.call_soon_threadsafe(broadcast, "process_change", {}))

    await start_all_schedulers()
    yield
    subprocess_shutdown()

app = FastAPI(title="CLAIRE", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes (public — no auth dependency)
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# API routes (all require auth when AUTH_ENABLED)
auth_dep = [Depends(get_current_user)]
admin_dep = [Depends(require_admin)]
app.include_router(tool_router, prefix="/api/tools", tags=["tools"], dependencies=auth_dep)
app.include_router(chatbot_router, prefix="/api/chatbots", tags=["chatbots"], dependencies=auth_dep)
app.include_router(pipeline_router, prefix="/api/pipelines", tags=["pipelines"], dependencies=auth_dep)
app.include_router(settings_router, prefix="/api/settings", tags=["settings"], dependencies=admin_dep)
app.include_router(file_router, prefix="/api", tags=["files"], dependencies=auth_dep)
app.include_router(trigger_router, prefix="/api/triggers", tags=["triggers"], dependencies=auth_dep)
app.include_router(reorder_router, prefix="/api", tags=["reorder"], dependencies=auth_dep)
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"], dependencies=auth_dep)
app.include_router(task_router, prefix="/api/tasks", tags=["tasks"], dependencies=auth_dep)
app.include_router(artifact_router, prefix="/api", tags=["artifacts"])


# WebSocket routes (at root, not prefixed)
app.websocket("/ws/tool-test")(ws_tool_test)
app.websocket("/ws/chat")(ws_chat)
app.websocket("/ws/lsp")(ws_lsp)
app.websocket("/ws/ai-assist")(ws_ai_assist)
app.websocket("/ws/ai-assist-pipeline")(ws_ai_assist_pipeline)
app.websocket("/ws/ai-assist-trigger")(ws_ai_assist_trigger)
app.websocket("/ws/task-execute")(ws_task_execute)


@app.get("/api/events")
async def sse_events(request: Request):
    if config.AUTH_ENABLED:
        # Check token from query param or Authorization header
        token = request.query_params.get("token", "")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if token:
            from services.auth_service import decode_token
            payload = decode_token(token)
            if not payload:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Invalid token"}, status_code=401)
        else:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return StreamingResponse(subscribe(), media_type="text/event-stream")


# Serve Vue SPA from ../frontend/dist if it exists
DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(DIST_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))



if __name__ == "__main__":
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)
    uvicorn.run(
        "main:app", host="0.0.0.0", port=8000, reload=True,
        reload_dirs=[backend_dir],
        reload_includes=["*.py"],
    )
