"""OAuth service — Google & Microsoft provider support."""

import secrets
import time
import urllib.parse
import httpx
import config

# ── Provider configuration ────────────────────────────────────────

PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scopes": "openid email profile",
    },
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scopes": "openid email profile User.Read",
    },
}


def _get_credentials(provider: str) -> tuple[str, str]:
    if provider == "google":
        return config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET
    if provider == "microsoft":
        return config.MICROSOFT_CLIENT_ID, config.MICROSOFT_CLIENT_SECRET
    return "", ""


def get_configured_providers() -> list[str]:
    """Return list of providers that have both client_id and client_secret set."""
    result = []
    for name in PROVIDERS:
        cid, secret = _get_credentials(name)
        if cid and secret:
            result.append(name)
    return result


# ── CSRF state store (in-memory, 10 min TTL) ─────────────────────

_states: dict[str, float] = {}


def generate_state() -> str:
    _cleanup_states()
    state = secrets.token_urlsafe(32)
    _states[state] = time.time()
    return state


def validate_state(state: str) -> bool:
    _cleanup_states()
    created = _states.pop(state, None)
    if created is None:
        return False
    return (time.time() - created) < 600  # 10 minutes


def _cleanup_states():
    now = time.time()
    expired = [s for s, t in _states.items() if now - t > 600]
    for s in expired:
        _states.pop(s, None)


# ── URL building ──────────────────────────────────────────────────

def build_auth_url(provider: str, redirect_uri: str) -> str:
    cfg = PROVIDERS[provider]
    client_id, _ = _get_credentials(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scopes"],
        "state": generate_state(),
    }
    if provider == "microsoft":
        params["response_mode"] = "query"
    return f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"


# ── Token exchange ────────────────────────────────────────────────

async def exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    cfg = PROVIDERS[provider]
    client_id, client_secret = _get_credentials(provider)
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=data)
        resp.raise_for_status()
        return resp.json()


# ── User info ─────────────────────────────────────────────────────

async def get_user_info(provider: str, access_token: str) -> dict:
    """Fetch user info and normalize to {id, email, name}."""
    cfg = PROVIDERS[provider]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    if provider == "google":
        return {
            "id": data.get("sub", ""),
            "email": data.get("email", ""),
            "name": data.get("name", ""),
        }
    if provider == "microsoft":
        return {
            "id": data.get("id", ""),
            "email": data.get("mail") or data.get("userPrincipalName", ""),
            "name": data.get("displayName", ""),
        }
    return {"id": "", "email": "", "name": ""}
