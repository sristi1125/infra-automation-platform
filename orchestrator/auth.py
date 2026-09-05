"""
API KEY AUTHENTICATION

Two ways to authenticate:
1. Permanent API keys (X-API-Key header) - for backend/CLI/service use,
   never exposed to a browser.
2. Session tokens (X-Session-Token header) - short-lived, issued after a
   successful login via /login. This is what the dashboard uses, so the
   permanent API keys never have to live in frontend code.

Keys are read from environment variables so real secrets never get
committed to git. For local dev, sensible defaults are provided so the
system works out of the box without extra setup.
"""

import os
import uuid
from functools import wraps
from flask import request, jsonify

# In a real deployment these come from environment variables / a secrets
# manager - never hardcoded. Defaults here are for local dev convenience
# only.
API_KEYS = {
    os.environ.get("OPERATOR_API_KEY", "dev-operator-key"): "operator",
    os.environ.get("VIEWER_API_KEY", "dev-viewer-key"): "viewer",
}

# Login credentials - also dev defaults only. In a real deployment these
# would be real user accounts, likely in Postgres with hashed passwords.
USERS = {
    "operator": {"password": os.environ.get("OPERATOR_PASSWORD", "operator123"), "role": "operator"},
    "viewer": {"password": os.environ.get("VIEWER_PASSWORD", "viewer123"), "role": "viewer"},
}

SESSION_TTL_SECONDS = 3600  # sessions expire after 1 hour


def create_session(redis_conn, username, role):
    """Issues a new random session token, storing it in Redis with an
    expiration. Returns the token."""
    token = str(uuid.uuid4())
    redis_conn.set(f"session:{token}", f"{username}:{role}", ex=SESSION_TTL_SECONDS)
    return token


def get_session(redis_conn, token):
    """Returns (username, role) for a valid session token, or None if
    the token is missing/expired/invalid."""
    raw = redis_conn.get(f"session:{token}")
    if raw is None:
        return None
    username, role = raw.decode().split(":")
    return username, role


def get_actor_and_role(redis_conn=None):
    """Returns (actor_label, role) for the current request, checking both
    a permanent API key and a session token. Returns (None, None) if
    neither is present/valid."""
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key in API_KEYS:
        role = API_KEYS[api_key]
        return role, role

    session_token = request.headers.get("X-Session-Token")
    if session_token and redis_conn is not None:
        session = get_session(redis_conn, session_token)
        if session:
            username, role = session
            return username, role

    return None, None


def require_role(minimum_role):
    """Decorator for Flask routes. minimum_role is 'viewer' or 'operator'.
    'operator' is required for anything that changes state; 'viewer' is
    enough for read-only endpoints (operator keys/sessions can also read)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            from app import redis_conn
            actor, role = get_actor_and_role(redis_conn)
            if role is None:
                return jsonify({"error": "missing or invalid credentials"}), 401

            if minimum_role == "operator" and role != "operator":
                return jsonify({"error": "this action requires an operator role"}), 403

            request.actor = actor
            return f(*args, **kwargs)
        return wrapped
    return decorator