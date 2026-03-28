import asyncio
import json
import os
import threading
import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from database import get_all, get_by_id, upsert, delete_by_id, now_iso
# RAG imports - lazy loaded, disabled when sentence-transformers/faiss not installed
try:
    from services.rag_service import build_index, query_index, delete_index
except ImportError:
    build_index = None  # type: ignore
    query_index = None  # type: ignore
    delete_index = None  # type: ignore
from services.llm import chat_stream
from services.memory_service import load_memory, save_memory
from event_bus import broadcast
from config import UPLOADS_DIR
from api.auth_deps import CurrentUser, get_current_user, check_permission, require_permission, get_accessible_resource_ids, ws_get_current_user
import config

router = APIRouter()


@router.get("")
async def list_chatbots(user: CurrentUser = Depends(get_current_user)):
    accessible_ids = get_accessible_resource_ids(user, "chatbots")
    all_chatbots = get_all("chatbots", "is_deleted = 0", order_by="sort_index")
    if accessible_ids is None:  # admin
        return all_chatbots
    return [c for c in all_chatbots if c["id"] in accessible_ids]


@router.get("/{chatbot_id}")
async def get_chatbot(chatbot_id: str):
    bot = get_by_id("chatbots", chatbot_id)
    if not bot:
        return {"error": "not found"}
    return bot


@router.post("")
async def save_chatbot(chatbot: dict, user: CurrentUser = Depends(get_current_user)):
    existing = get_by_id("chatbots", chatbot.get("id", ""))
    action = "edit" if existing else "create"
    if not check_permission(user, "chatbots", action):
        from fastapi import HTTPException
        raise HTTPException(403, "Permission denied")
    chatbot["updated_at"] = now_iso()
    result = upsert("chatbots", chatbot)
    return {"response": result["id"]}


@router.delete("/{chatbot_id}")
async def delete_chatbot(chatbot_id: str, user: CurrentUser = Depends(require_permission("chatbots", "delete"))):
    # Soft delete
    bot = get_by_id("chatbots", chatbot_id)
    if bot:
        bot["is_deleted"] = True
        upsert("chatbots", bot)
    if delete_index:
        delete_index(chatbot_id)
    return {"response": "ok"}


def _collect_documents(bot: dict) -> list[dict]:
    """Collect documents from the configured source."""
    documents = []
    source_type = bot.get("source_type", "filesystem")

    if source_type == "filesystem":
        folder = bot.get("source_folder", "")
        if folder and os.path.isdir(folder):
            exts = {".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".css",
                    ".xml", ".csv", ".sql", ".cs", ".java", ".go", ".rs", ".yaml", ".yml"}
            for root, _, files in os.walk(folder):
                for fname in files:
                    if any(fname.endswith(ext) for ext in exts):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                            documents.append({"text": text, "source": fpath})
                        except Exception:
                            pass

    elif source_type == "text":
        texts = bot.get("source_texts", [])
        for i, text in enumerate(texts):
            if text.strip():
                documents.append({"text": text, "source": f"text-{i}"})

    elif source_type == "upload":
        upload_dir = os.path.join(UPLOADS_DIR, bot["id"])
        if os.path.isdir(upload_dir):
            for fname in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    documents.append({"text": text, "source": fname})
                except Exception:
                    pass

    elif source_type == "github":
        documents = _collect_github_documents(bot)

    return documents


def _collect_github_documents(bot: dict) -> list[dict]:
    """Fetch files from a GitHub repo via the Trees API + raw content."""
    owner = bot.get("github_owner", "")
    repo = bot.get("github_repo", "")
    branch = bot.get("github_branch", "main") or "main"
    folder = bot.get("github_folder", "").strip("/")
    chatbot_id = bot.get("id", "")

    if not owner or not repo:
        return []

    exts = {".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".css",
            ".xml", ".csv", ".sql", ".cs", ".java", ".go", ".rs", ".rst",".yaml", ".yml",
            ".jsx", ".tsx", ".vue", ".svelte", ".sh", ".bat", ".toml", ".cfg", ".ini"}

    token = config.GITHUB_TOKEN
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Get the full tree in one call
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = httpx.get(tree_url, headers=headers, timeout=30)
    resp.raise_for_status()
    tree = resp.json()

    # Filter to supported file types, optionally within a subfolder
    paths = []
    for item in tree.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item["path"]
        if folder and not path.startswith(folder + "/"):
            continue
        if any(path.endswith(ext) for ext in exts):
            paths.append(path)

    documents = []
    broadcast("index_progress", {
        "chatbot_id": chatbot_id,
        "current": 0,
        "total": len(paths),
        "status": "fetching",
    })

    for i, path in enumerate(paths):
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        try:
            r = httpx.get(raw_url, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=30)
            r.raise_for_status()
            documents.append({"text": r.text, "source": f"{owner}/{repo}/{path}"})
        except Exception:
            pass
        broadcast("index_progress", {
            "chatbot_id": chatbot_id,
            "current": i + 1,
            "total": len(paths),
            "status": "fetching",
        })

    return documents


def _run_index(chatbot_id: str, documents: list[dict]):
    """Run indexing in a background thread (CPU/GPU-bound work)."""
    try:
        if not build_index:
            broadcast("index_error", {"chatbot_id": chatbot_id, "error": "RAG dependencies not installed"})
            return
        count = build_index(chatbot_id, documents)
        broadcast("index_complete", {"chatbot_id": chatbot_id, "count": count})
    except Exception as e:
        broadcast("index_error", {"chatbot_id": chatbot_id, "error": str(e)})


@router.post("/{chatbot_id}/index")
async def reindex(chatbot_id: str):
    """Reindex documents for a chatbot."""
    bot = get_by_id("chatbots", chatbot_id)
    if not bot:
        return {"error": "not found"}

    documents = _collect_documents(bot)
    if not documents:
        return {"response": "no documents found", "count": 0}

    threading.Thread(target=_run_index, args=(chatbot_id, documents), daemon=True).start()
    return {"response": "indexing", "count": -1}


# ── Chat histories ────────────────────────────────────────────────

@router.get("/{chatbot_id}/histories")
async def list_histories(chatbot_id: str):
    return get_all("chat_histories", "chatbot_id = ?", (chatbot_id,))


@router.post("/{chatbot_id}/histories")
async def save_history(chatbot_id: str, history: dict):
    history["chatbot_id"] = chatbot_id
    history["updated_at"] = now_iso()
    result = upsert("chat_histories", history)
    return {"response": result["id"]}


@router.delete("/histories/{history_id}")
async def delete_history(history_id: str):
    delete_by_id("chat_histories", history_id)
    return {"response": "ok"}


# ── WebSocket chat ────────────────────────────────────────────────

async def ws_chat(ws: WebSocket):
    try:
        user = await ws_get_current_user(ws)
    except Exception:
        return
    await ws.accept()
    try:
        raw = await ws.receive_text()
        data = json.loads(raw)

        chatbot_id = data.get("chatbot_id", "")
        query = data.get("query", "")
        history_id = data.get("history_id", "")

        bot = get_by_id("chatbots", chatbot_id)
        if not bot:
            await ws.send_text(json.dumps({"type": "error", "text": "Chatbot not found"}))
            return

        model = bot.get("model", "")

        # Load conversation history
        mem = load_memory(history_id) if history_id else []
        messages = mem[-20:]  # Keep last 20 messages for context

        # RAG: query the index for context (run in thread to avoid blocking async loop)
        context = ""
        sources = []
        if query_index:
            results = await asyncio.to_thread(query_index, chatbot_id, query)
            context = "\n\n".join([r["text"] for r in results])
            sources = list(set(r["source"] for r in results if r.get("source")))

        system_prompt = bot.get("description", "")
        if context:
            system_prompt += f"\n\nUse the following context to answer the user's question:\n\n{context}"

        messages.append({"role": "user", "content": query})

        full_response = ""
        async for chunk in chat_stream(messages, model, system_prompt):
            await ws.send_text(json.dumps(chunk))
            if chunk.get("type") == "text":
                full_response += chunk.get("text", "")

        if sources:
            await ws.send_text(json.dumps({"type": "sources", "sources": sources}))

        # Save to memory (reuse the already-loaded mem to avoid second file read)
        if history_id:
            mem.append({"role": "user", "content": query})
            mem.append({"role": "assistant", "content": full_response})
            save_memory(history_id, mem)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
