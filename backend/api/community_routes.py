"""Community proxy routes — forward requests to the community/support site to avoid CORS."""

import httpx
from fastapi import APIRouter, HTTPException, Query
import config

router = APIRouter()


def _base_url() -> str:
    url = config.COMMUNITY_URL.rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="Community URL not configured")
    return url


@router.get("/items")
async def browse_items(
    type: str = Query("", description="Filter by item_type"),
    search: str = Query("", description="Search"),
    sort: str = Query("newest", description="Sort"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    base = _base_url()
    params = {"page": page, "limit": limit, "sort": sort}
    if type:
        params["type"] = type
    if search:
        params["search"] = search
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/items/", params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Community site error")
    return resp.json()


@router.get("/items/{item_id}")
async def get_item(item_id: str):
    base = _base_url()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/items/{item_id}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Item not found")
    return resp.json()


@router.get("/items/{item_id}/download")
async def download_item(item_id: str):
    base = _base_url()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/items/{item_id}/download")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Download failed")
    return resp.json()


@router.get("/status")
async def community_status():
    """Check if community URL is configured and reachable."""
    url = config.COMMUNITY_URL.rstrip("/")
    if not url:
        return {"configured": False, "reachable": False, "url": ""}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/api/items/stats")
        return {"configured": True, "reachable": resp.status_code == 200, "url": url}
    except Exception:
        return {"configured": True, "reachable": False, "url": url}
