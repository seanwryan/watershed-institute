"""
Staff password protection for the whole web app.

Set STAFF_PASSWORD (and optionally STAFF_USERNAME, default "staff") in the
host's environment to require HTTP Basic sign-in on every page and API.
The browser shows its own sign-in prompt and remembers it for the session.

/health stays open so the host's uptime check keeps working; it returns no data.
When STAFF_PASSWORD is unset (local development) nothing is required, and a
warning is logged so an unprotected deployment is visible in the host logs.

Use HTTPS (Render provides it); Basic auth sends the password with each request.
"""
from __future__ import annotations

import hmac
import logging
import os

from flask import Response, request

OPEN_PATHS = frozenset({"/health"})
REALM = "StreamWatch staff"

log = logging.getLogger(__name__)


def staff_credentials():
    """Return (username, password) when protection is configured, else None."""
    password = os.getenv("STAFF_PASSWORD") or ""
    if not password.strip():
        return None
    username = (os.getenv("STAFF_USERNAME") or "staff").strip() or "staff"
    return username, password


def _matches(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def is_authorized(auth, creds) -> bool:
    if creds is None:
        return True
    if auth is None or auth.type != "basic":
        return False
    username, password = creds
    # Evaluate both comparisons to avoid leaking which one failed via timing.
    user_ok = _matches(auth.username or "", username)
    pass_ok = _matches(auth.password or "", password)
    return user_ok and pass_ok


def _challenge() -> Response:
    return Response(
        "Sign-in required.",
        401,
        {"WWW-Authenticate": f'Basic realm="{REALM}", charset="UTF-8"', "Cache-Control": "no-store"},
    )


def register_staff_auth(app):
    """Attach the sign-in check. Registered first so it runs before other hooks."""
    if staff_credentials() is None:
        log.warning("STAFF_PASSWORD is not set: the web app is not password-protected.")

    @app.before_request
    def _require_staff_login():
        if request.path in OPEN_PATHS:
            return None
        creds = staff_credentials()
        if is_authorized(request.authorization, creds):
            return None
        return _challenge()
