from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
import time as _time
from typing import Any, Dict, Optional

BJT = timezone(timedelta(hours=8))

from fastapi import Request
from fastapi.responses import RedirectResponse

import database

SESSION_STORE: Dict[str, Dict[str, Any]] = {}


def create_session(user: Dict[str, Any]) -> str:
    """Create a session for the given user dict, return session_id."""
    session_id = uuid.uuid4().hex
    SESSION_STORE[session_id] = {
        "user_id": user["id"],
        "username": user["username"],
        "is_admin": bool(user.get("is_admin", 0)),
        "points": user.get("points", 0),
        "created_at": datetime.now(BJT).replace(tzinfo=None).isoformat(),
    }
    return session_id


SESSION_TTL = 86400

def get_session_user(session_id: str) -> Optional[Dict[str, Any]]:
    """Validate session and return user info dict, or None if expired/invalid."""
    if not session_id:
        return None
    data = SESSION_STORE.get(session_id)
    if data is None:
        return None
    created = data.get("created_at", "")
    if created:
        try:
            from datetime import datetime
            ct = datetime.fromisoformat(created)
            age = (_time.time() - ct.timestamp())
            if age > SESSION_TTL:
                SESSION_STORE.pop(session_id, None)
                return None
        except Exception:
            pass
    user = database.get_user_by_id(data["user_id"])
    if user is None:
        SESSION_STORE.pop(session_id, None)
        return None
    user["is_admin"] = bool(user.get("is_admin", 0))
    return user


def destroy_session(session_id: str) -> None:
    """Remove a session from the store."""
    SESSION_STORE.pop(session_id, None)


def login_user(username: str, password: str) -> Optional[str]:
    """Authenticate credentials, create session, return session_id or None."""
    user = database.authenticate_user(username, password)
    if user is None:
        return None
    return create_session(user)


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Get current user from session, or None if not authenticated."""
    session_id = request.cookies.get("session_id")
    return get_session_user(session_id)


def require_login(request: Request) -> Dict[str, Any]:
    """Get current user. Returns user dict or None (caller must handle redirect)."""
    user = get_current_user(request)
    if user is None:
        return None
    request.state.user = user
    return user


def require_admin(request: Request) -> Optional[Dict[str, Any]]:
    """Get current admin user. Returns user dict or None (caller must handle)."""
    user = require_login(request)
    if user is None:
        return None
    if not user.get("is_admin"):
        return None
    return user


def check_and_deduct(user_id: int, action_type: str, config: dict, detail: str = "", is_admin: bool = False) -> bool:
    """Check if user has enough points, deduct if so. Return True on success."""
    cost_key = f"{action_type}_points_cost"
    amount = config.get(cost_key, 1)
    return database.deduct_points(user_id, amount, action_type, detail)
