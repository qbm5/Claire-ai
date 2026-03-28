from fastapi import APIRouter
from database import update_where

router = APIRouter()

ALLOWED_TABLES = {"chatbots", "tools", "pipelines", "triggers"}


@router.post("/{table}/reorder")
async def reorder(table: str, body: dict):
    if table not in ALLOWED_TABLES:
        return {"error": f"table '{table}' not allowed"}
    ids = body.get("ids", [])
    if not ids:
        return {"error": "ids list is empty"}
    for index, item_id in enumerate(ids):
        update_where(table, {"sort_index": index}, where="id = ?", params=(item_id,))
    return {"response": "ok"}
