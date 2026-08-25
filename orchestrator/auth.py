"""
API KEY AUTHENTICATION

Simple token-based auth: every request must include a valid API key in
the 'X-API-Key' header. Each key is tagged with a role - 'viewer' (read
only) or 'operator' (can trigger actions) - so not every key grants the
same level of access.

Keys are read from environment variables so real secrets never get
committed to git. For local dev, sensible defaults are provided so the
system works out of the box without extra setup.
"""

import os
from functools import wraps
from flask import request, jsonify

# In a real deployment these come from environment variables / a secrets
# manager - never hardcoded. Defaults here are for local dev convenience
# only.
API_KEYS = {
    os.environ.get("OPERATOR_API_KEY", "dev-operator-key"): "operator",
    os.environ.get("VIEWER_API_KEY", "dev-viewer-key"): "viewer",
}


def get_actor_and_role():
    """Returns (actor_label, role) for the current request, or (None, None)
    if no valid key was provided."""
    key = request.headers.get("X-API-Key")
    if key is None or key not in API_KEYS:
        return None, None
    role = API_KEYS[key]
    # actor label is just the role for now - could be a real username
    # per key in a more complete version
    return role, role


def require_role(minimum_role):
    """Decorator for Flask routes. minimum_role is 'viewer' or 'operator'.
    'operator' is required for anything that changes state; 'viewer' is
    enough for read-only endpoints (operator keys can also read)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            actor, role = get_actor_and_role()
            if role is None:
                return jsonify({"error": "missing or invalid API key"}), 401

            if minimum_role == "operator" and role != "operator":
                return jsonify({"error": "this action requires an operator role"}), 403

            request.actor = actor
            return f(*args, **kwargs)
        return wrapped
    return decorator