"""Authentication routes — login, register, user management, permissions."""

import json
import urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from database import get_all, get_by_id, upsert, delete_by_id, count
from db.helpers import get_uid, now_iso
from services.auth_service import hash_password, verify_password, create_token
from services.oauth_service import (
    PROVIDERS, get_configured_providers, validate_state,
    build_auth_url, exchange_code, get_user_info,
)
from api.auth_deps import (
    CurrentUser, get_current_user, require_admin, require_owner,
    get_accessible_resource_ids,
)
import config
from config import RESOURCE_TYPES

router = APIRouter()


def _seed_user_permissions(user_id: str, grant_all: bool = False):
    """Create user_permissions rows for a new user.
    grant_all=True gives full create/edit/delete (used for migration of existing users).
    """
    now = now_iso()
    for rt in RESOURCE_TYPES:
        upsert("user_permissions", {
            "id": get_uid(),
            "user_id": user_id,
            "resource_type": rt,
            "can_create": grant_all,
            "can_edit": grant_all,
            "can_delete": grant_all,
            "created_at": now,
            "updated_at": now,
        })


def _seed_user_resource_access(user_id: str):
    """Grant a user access to all existing resources (used for migration)."""
    now = now_iso()
    for rt in RESOURCE_TYPES:
        for item in get_all(rt):
            # Skip system pipeline
            if rt == "pipelines" and item.get("id") == "__tool_runs__":
                continue
            upsert("user_resource_access", {
                "id": get_uid(),
                "user_id": user_id,
                "resource_type": rt,
                "resource_id": item["id"],
                "created_at": now,
            })


def _cleanup_user_permissions(user_id: str):
    """Remove all permission and access rows for a user."""
    for row in get_all("user_permissions", "user_id = ?", (user_id,)):
        delete_by_id("user_permissions", row["id"])
    for row in get_all("user_resource_access", "user_id = ?", (user_id,)):
        delete_by_id("user_resource_access", row["id"])


# ── Public routes (no auth required) ─────────────────────────────

@router.get("/status")
async def auth_status():
    has_owner = count("users", "role = ?", ("owner",)) > 0 if config.AUTH_ENABLED else False
    return {
        "auth_enabled": config.AUTH_ENABLED,
        "has_owner": has_owner,
        "needs_setup": config.AUTH_ENABLED and not has_owner,
        "oauth_providers": get_configured_providers() if config.AUTH_ENABLED else [],
    }


@router.post("/register")
async def register(body: dict):
    """Register the first user as Owner. Only works when no users exist."""
    if not config.AUTH_ENABLED:
        raise HTTPException(400, "Authentication is not enabled")

    if count("users") > 0:
        raise HTTPException(400, "Registration closed — users already exist")

    username = body.get("username", "").strip()
    email = body.get("email", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    user_id = get_uid()
    now = now_iso()
    user = {
        "id": user_id,
        "username": username,
        "email": email,
        "password_hash": hash_password(password),
        "role": "owner",
        "is_active": True,
        "display_name": username,
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }
    upsert("users", user)

    token = create_token(user_id, "owner")
    return {
        "token": token,
        "user": {"id": user_id, "username": username, "email": email, "role": "owner"},
    }


@router.post("/login")
async def login(body: dict):
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    users = get_all("users", "username = ?", (username,))
    if not users:
        raise HTTPException(401, "Invalid credentials")

    user = users[0]
    if not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")

    if not user.get("is_active", True):
        raise HTTPException(403, "Account disabled")

    token = create_token(user["id"], user["role"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user["role"],
        },
        "must_change_password": bool(user.get("must_change_password", False)),
    }


@router.get("/me")
async def get_me(user: CurrentUser = Depends(get_current_user)):
    if user.id == "default":
        return {
            "id": "default", "username": "default", "email": "",
            "role": "owner", "display_name": "default",
            "must_change_password": False,
            "permissions": {}, "resource_access": {},
        }

    db_user = get_by_id("users", user.id)
    if not db_user:
        raise HTTPException(401, "User not found")

    # Build per-user permissions map
    permissions = {}
    resource_access = {}
    if not user.is_admin:
        for perm in get_all("user_permissions", "user_id = ?", (user.id,)):
            permissions[perm["resource_type"]] = {
                "can_create": bool(perm.get("can_create", False)),
                "can_edit": bool(perm.get("can_edit", False)),
                "can_delete": bool(perm.get("can_delete", False)),
            }
        # Build resource access map
        for rt in RESOURCE_TYPES:
            ids = get_accessible_resource_ids(user, rt)
            resource_access[rt] = list(ids) if ids is not None else []

    return {
        "id": db_user["id"],
        "username": db_user["username"],
        "email": db_user.get("email", ""),
        "role": db_user["role"],
        "display_name": db_user.get("display_name", ""),
        "must_change_password": bool(db_user.get("must_change_password", False)),
        "permissions": permissions,
        "resource_access": resource_access,
    }


# ── OAuth routes ──────────────────────────────────────────────────

@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str, request: Request):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")
    if provider not in get_configured_providers():
        raise HTTPException(400, f"Provider {provider} is not configured")
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/auth/oauth/{provider}/callback"
    url = build_auth_url(provider, redirect_uri)
    return {"url": url}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, code: str = "", state: str = "", error: str = ""):
    login_url = "/login"

    if error:
        return RedirectResponse(f"{login_url}?error={urllib.parse.quote(error)}")

    if provider not in PROVIDERS or provider not in get_configured_providers():
        return RedirectResponse(f"{login_url}?error=Unknown+provider")

    if not code or not state:
        return RedirectResponse(f"{login_url}?error=Missing+code+or+state")

    if not validate_state(state):
        return RedirectResponse(f"{login_url}?error=Invalid+or+expired+state")

    try:
        redirect_uri = str(request.base_url).rstrip("/") + f"/api/auth/oauth/{provider}/callback"
        token_data = await exchange_code(provider, code, redirect_uri)
        access_token = token_data.get("access_token", "")
        if not access_token:
            return RedirectResponse(f"{login_url}?error=No+access+token+received")

        user_info = await get_user_info(provider, access_token)
        oauth_id = user_info.get("id", "")
        oauth_email = user_info.get("email", "")
        oauth_name = user_info.get("name", "")

        if not oauth_id:
            return RedirectResponse(f"{login_url}?error=Could+not+get+user+info")

        # 1. Look up by (oauth_provider, oauth_id)
        existing = get_all("users", "oauth_provider = ? AND oauth_id = ?", (provider, oauth_id))
        user = existing[0] if existing else None

        # 2. If not found, look up by email
        if not user and oauth_email:
            by_email = get_all("users", "email = ?", (oauth_email,))
            if by_email:
                user = by_email[0]
                # Link the OAuth identity to the existing user
                user["oauth_provider"] = provider
                user["oauth_id"] = oauth_id
                user["updated_at"] = now_iso()
                upsert("users", user)

        # 3. If not found, create new user
        is_new_user = False
        if not user:
            has_users = count("users") > 0
            user_id = get_uid()
            now = now_iso()
            user = {
                "id": user_id,
                "username": oauth_name or oauth_email.split("@")[0] if oauth_email else f"user_{user_id[:6]}",
                "email": oauth_email,
                "password_hash": "",
                "role": "owner" if not has_users else "user",
                "is_active": True,
                "display_name": oauth_name or "",
                "must_change_password": False,
                "oauth_provider": provider,
                "oauth_id": oauth_id,
                "created_at": now,
                "updated_at": now,
            }
            upsert("users", user)
            is_new_user = True

        # Seed permissions for new non-admin OAuth users
        if is_new_user and user["role"] == "user":
            _seed_user_permissions(user["id"])

        if not user.get("is_active", True):
            return RedirectResponse(f"{login_url}?error=Account+disabled")

        jwt = create_token(user["id"], user["role"])
        user_json = json.dumps({
            "id": user["id"],
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "role": user["role"],
        })
        params = urllib.parse.urlencode({"oauth_token": jwt, "oauth_user": user_json})
        return RedirectResponse(f"{login_url}?{params}")

    except Exception as e:
        return RedirectResponse(f"{login_url}?error={urllib.parse.quote(str(e))}")


# ── Admin/Owner routes ───────────────────────────────────────────

@router.get("/users")
async def list_users(_: CurrentUser = Depends(require_admin)):
    users = get_all("users")
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "email": u.get("email", ""),
            "role": u["role"],
            "is_active": u.get("is_active", True),
            "display_name": u.get("display_name", ""),
            "must_change_password": bool(u.get("must_change_password", False)),
            "oauth_provider": u.get("oauth_provider", ""),
            "created_at": u.get("created_at", ""),
        }
        for u in users
    ]


@router.post("/users")
async def create_user(body: dict, admin: CurrentUser = Depends(require_admin)):
    username = body.get("username", "").strip()
    email = body.get("email", "").strip()
    password = body.get("password", "")
    role = body.get("role", "user")
    display_name = body.get("display_name", "").strip() or username
    must_change_password = body.get("must_change_password", False)

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    # Only owner can create admins
    if role == "admin" and not admin.is_owner:
        raise HTTPException(403, "Only the owner can create admin accounts")

    if role == "owner":
        raise HTTPException(400, "Cannot create another owner")

    # Check uniqueness
    existing = get_all("users", "username = ?", (username,))
    if existing:
        raise HTTPException(400, "Username already taken")

    user_id = get_uid()
    now = now_iso()
    user = {
        "id": user_id,
        "username": username,
        "email": email,
        "password_hash": hash_password(password),
        "role": role,
        "is_active": True,
        "display_name": display_name,
        "must_change_password": must_change_password,
        "created_at": now,
        "updated_at": now,
    }
    upsert("users", user)

    # Seed per-user permissions (all deny by default) for regular users
    if role == "user":
        _seed_user_permissions(user_id)

    return {
        "id": user_id,
        "username": username,
        "email": email,
        "role": role,
        "display_name": display_name,
        "must_change_password": must_change_password,
        "is_active": True,
        "created_at": now,
    }


@router.put("/users/{user_id}/role")
async def change_role(user_id: str, body: dict, _: CurrentUser = Depends(require_owner)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    new_role = body.get("role", "")
    if new_role not in ("admin", "user"):
        raise HTTPException(400, "Role must be 'admin' or 'user'")

    if user["role"] == "owner":
        raise HTTPException(400, "Cannot change the owner's role")

    user["role"] = new_role
    user["updated_at"] = now_iso()
    upsert("users", user)
    return {"response": "ok"}


@router.put("/users/{user_id}/active")
async def toggle_active(user_id: str, body: dict, admin: CurrentUser = Depends(require_admin)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user["role"] == "owner":
        raise HTTPException(400, "Cannot deactivate the owner")

    if user["id"] == admin.id:
        raise HTTPException(400, "Cannot deactivate yourself")

    user["is_active"] = body.get("is_active", True)
    user["updated_at"] = now_iso()
    upsert("users", user)
    return {"response": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, owner: CurrentUser = Depends(require_owner)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user["role"] == "owner":
        raise HTTPException(400, "Cannot delete the owner")

    # Clean up permission/access rows
    _cleanup_user_permissions(user_id)
    delete_by_id("users", user_id)
    return {"response": "ok"}


# ── Per-user permission management (admin only) ──────────────────

@router.get("/users/{user_id}/permissions")
async def get_user_permissions(user_id: str, _: CurrentUser = Depends(require_admin)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return get_all("user_permissions", "user_id = ?", (user_id,))


@router.post("/users/{user_id}/permissions")
async def save_user_permissions(user_id: str, body: list[dict], _: CurrentUser = Depends(require_admin)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Delete existing and re-create
    for row in get_all("user_permissions", "user_id = ?", (user_id,)):
        delete_by_id("user_permissions", row["id"])

    now = now_iso()
    for perm in body:
        upsert("user_permissions", {
            "id": get_uid(),
            "user_id": user_id,
            "resource_type": perm.get("resource_type", ""),
            "can_create": perm.get("can_create", False),
            "can_edit": perm.get("can_edit", False),
            "can_delete": perm.get("can_delete", False),
            "created_at": now,
            "updated_at": now,
        })
    return {"response": "ok"}


@router.get("/users/{user_id}/access")
async def get_user_access(user_id: str, _: CurrentUser = Depends(require_admin)):
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")
    rows = get_all("user_resource_access", "user_id = ?", (user_id,))
    # Group by resource_type
    result = {}
    for rt in RESOURCE_TYPES:
        result[rt] = [r["resource_id"] for r in rows if r["resource_type"] == rt]
    return result


@router.post("/users/{user_id}/access")
async def save_user_access(user_id: str, body: dict, _: CurrentUser = Depends(require_admin)):
    """Replace resource access grants. Body: { "tools": ["id1","id2"], ... }"""
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Delete existing access rows for the types being updated
    for row in get_all("user_resource_access", "user_id = ?", (user_id,)):
        if row["resource_type"] in body:
            delete_by_id("user_resource_access", row["id"])

    # Insert new rows
    now = now_iso()
    for rt, ids in body.items():
        if rt not in RESOURCE_TYPES:
            continue
        for resource_id in ids:
            upsert("user_resource_access", {
                "id": get_uid(),
                "user_id": user_id,
                "resource_type": rt,
                "resource_id": resource_id,
                "created_at": now,
            })
    return {"response": "ok"}


# ── Self-service endpoints ────────────────────────────────────────

@router.put("/me/password")
async def change_own_password(body: dict, user: CurrentUser = Depends(get_current_user)):
    """User changes own password. Requires current + new password."""
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")

    if not current_password or not new_password:
        raise HTTPException(400, "Current and new password are required")

    if len(new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")

    db_user = get_by_id("users", user.id)
    if not db_user:
        raise HTTPException(401, "User not found")

    if not verify_password(current_password, db_user.get("password_hash", "")):
        raise HTTPException(400, "Current password is incorrect")

    db_user["password_hash"] = hash_password(new_password)
    db_user["must_change_password"] = False
    db_user["updated_at"] = now_iso()
    upsert("users", db_user)
    return {"response": "ok"}


@router.put("/me/profile")
async def update_own_profile(body: dict, user: CurrentUser = Depends(get_current_user)):
    """User updates own display name."""
    db_user = get_by_id("users", user.id)
    if not db_user:
        raise HTTPException(401, "User not found")

    display_name = body.get("display_name", "").strip()
    if display_name:
        db_user["display_name"] = display_name
        db_user["updated_at"] = now_iso()
        upsert("users", db_user)
    return {"response": "ok"}


# ── Admin password management ────────────────────────────────────

@router.put("/users/{user_id}/password")
async def admin_reset_password(user_id: str, body: dict, _: CurrentUser = Depends(require_admin)):
    """Admin resets a user's password and/or sets force_change flag."""
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user["role"] == "owner":
        raise HTTPException(400, "Cannot reset the owner's password via this endpoint")

    new_password = body.get("new_password", "")
    force_change = body.get("force_change", False)

    if new_password:
        if len(new_password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        user["password_hash"] = hash_password(new_password)

    user["must_change_password"] = force_change
    user["updated_at"] = now_iso()
    upsert("users", user)
    return {"response": "ok"}


# ── Legacy permission matrix (backward compat) ───────────────────

@router.get("/permissions")
async def get_permissions(_: CurrentUser = Depends(require_admin)):
    return get_all("role_permissions")


@router.post("/permissions")
async def save_permissions(body: list[dict], _: CurrentUser = Depends(require_admin)):
    for perm in body:
        perm["updated_at"] = now_iso()
        upsert("role_permissions", perm)
    return {"response": "ok"}
