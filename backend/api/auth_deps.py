"""Authentication dependencies for FastAPI route injection."""

from fastapi import Request, WebSocket, HTTPException, Depends
from database import get_by_id, get_all
import config


class CurrentUser:
    def __init__(self, id: str, username: str, role: str,
                 display_name: str = "", must_change_password: bool = False):
        self.id = id
        self.username = username
        self.role = role
        self.display_name = display_name
        self.must_change_password = must_change_password

    @property
    def is_admin(self) -> bool:
        return self.role in ("admin", "owner")

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


OPEN_USER = CurrentUser("default", "default", "owner")


async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate the current user from the request.
    When AUTH_ENABLED=false, returns OPEN_USER (synthetic owner).
    """
    if not config.AUTH_ENABLED:
        return OPEN_USER

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header[7:]
    from services.auth_service import decode_token
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub", "")
    user = get_by_id("users", user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    return CurrentUser(
        user["id"], user["username"], user["role"],
        display_name=user.get("display_name", ""),
        must_change_password=bool(user.get("must_change_password", False)),
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_owner(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


def check_permission(user: CurrentUser, resource_type: str, action: str) -> bool:
    """Check if user has permission for the given resource/action.
    Admins and owners always have full access.
    Uses per-user user_permissions table.
    """
    if user.is_admin:
        return True

    col = f"can_{action}"
    perms = get_all("user_permissions", "user_id = ? AND resource_type = ?", (user.id, resource_type))
    if not perms:
        return False  # no permission row = deny by default
    return bool(perms[0].get(col, False))


def require_permission(resource_type: str, action: str):
    """Returns a dependency that checks a specific permission."""
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not check_permission(user, resource_type, action):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return _dep


def check_resource_access(user: CurrentUser, resource_type: str, resource_id: str) -> bool:
    """Check if user has access to a specific resource instance.
    Admins always have access.
    """
    if user.is_admin:
        return True
    rows = get_all(
        "user_resource_access",
        "user_id = ? AND resource_type = ? AND resource_id = ?",
        (user.id, resource_type, resource_id),
    )
    return len(rows) > 0


def get_accessible_resource_ids(user: CurrentUser, resource_type: str):
    """Returns list of resource IDs user can access, or None for admins (no filter)."""
    if user.is_admin:
        return None
    rows = get_all("user_resource_access", "user_id = ? AND resource_type = ?", (user.id, resource_type))
    return set(r["resource_id"] for r in rows)


async def ws_get_current_user(websocket: WebSocket) -> CurrentUser:
    """Extract user from WebSocket ?token= query param."""
    if not config.AUTH_ENABLED:
        return OPEN_USER

    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        raise HTTPException(status_code=401, detail="Not authenticated")

    from services.auth_service import decode_token
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub", "")
    user = get_by_id("users", user_id)
    if not user or not user.get("is_active", True):
        await websocket.close(code=4003, reason="Account disabled")
        raise HTTPException(status_code=403, detail="Account disabled")

    return CurrentUser(
        user["id"], user["username"], user["role"],
        display_name=user.get("display_name", ""),
        must_change_password=bool(user.get("must_change_password", False)),
    )
