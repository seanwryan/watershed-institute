"""
Staff password protection for the whole web app.

Set STAFF_PASSWORD (and optionally STAFF_USERNAME, default "staff") in the
host's environment. Then:
  - people sign in on /login (a normal page, so it works in every browser,
    including embedded ones that don't show HTTP sign-in pop-ups) and stay
    signed in for STAFF_SESSION_HOURS (default 12) or until they sign out;
  - scripts can still send HTTP Basic credentials with each request;
  - pages redirect to /login, API/export requests get 401.

/health stays open for the host's uptime check (it returns no data), as do
/login and /static. When STAFF_PASSWORD is unset (local development) nothing is
required and a warning is logged.

The session cookie is signed with SECRET_KEY, or a key derived from
STAFF_PASSWORD when SECRET_KEY is unset, so it survives restarts and changing
the password signs everyone out. Cookies are HttpOnly, SameSite=Lax, and
Secure when served over HTTPS.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import timedelta
from urllib.parse import urlparse

from flask import Response, jsonify, redirect, render_template, request, session, url_for

OPEN_PATHS = frozenset({"/health", "/login", "/logout"})
OPEN_PREFIXES = ("/static/",)
REALM = "StreamWatch staff"
SESSION_KEY = "staff_signed_in"

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


def credentials_ok(username: str, password: str, creds) -> bool:
    if creds is None:
        return True
    # Evaluate both comparisons to avoid leaking which one failed via timing.
    user_ok = _matches(username or "", creds[0])
    pass_ok = _matches(password or "", creds[1])
    return user_ok and pass_ok


def is_authorized(auth, creds) -> bool:
    """HTTP Basic check (kept for scripts and API clients)."""
    if creds is None:
        return True
    if auth is None or auth.type != "basic":
        return False
    return credentials_ok(auth.username, auth.password, creds)


def _session_marker(creds) -> str:
    """Changes when the password changes, which ends existing sessions."""
    return hashlib.sha256(("staff-session:" + creds[0] + ":" + creds[1]).encode("utf-8")).hexdigest()[:32]


def _signed_in(creds) -> bool:
    return creds is not None and session.get(SESSION_KEY) == _session_marker(creds)


def _safe_next(target: str | None) -> str:
    """Only allow same-site relative paths as the post-sign-in destination."""
    if not target:
        return "/"
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def _wants_page() -> bool:
    if request.path.startswith("/api/") or request.path.startswith("/export/") or request.path.endswith(".csv"):
        return False
    return request.method in ("GET", "HEAD")


def _challenge() -> Response:
    resp = jsonify({"error": "Sign-in required."}) if request.path.startswith("/api/") else Response("Sign-in required.")
    resp.status_code = 401
    resp.headers["WWW-Authenticate"] = f'Basic realm="{REALM}", charset="UTF-8"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _configure_sessions(app, creds) -> None:
    if not app.secret_key:
        secret = os.getenv("SECRET_KEY") or ""
        if not secret and creds is not None:
            secret = hashlib.sha256(("streamwatch-secret:" + creds[1]).encode("utf-8")).hexdigest()
        app.secret_key = secret or os.urandom(32).hex()
    hours = float(os.getenv("STAFF_SESSION_HOURS") or 12)
    # Flask pre-populates these keys, so assign rather than setdefault.
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=hours)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def register_staff_auth(app):
    """Attach sign-in routes and the check. Registered first so it runs before other hooks."""
    creds_at_start = staff_credentials()
    if creds_at_start is None:
        log.warning("STAFF_PASSWORD is not set: the web app is not password-protected.")
    _configure_sessions(app, creds_at_start)

    @app.context_processor
    def _inject_staff_auth():
        creds = staff_credentials()
        return {"staff_auth_enabled": creds is not None, "staff_signed_in": _signed_in(creds)}

    @app.before_request
    def _require_staff_login():
        app.config["SESSION_COOKIE_SECURE"] = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
        if request.path in OPEN_PATHS or request.path.startswith(OPEN_PREFIXES):
            return None
        creds = staff_credentials()
        if creds is None or _signed_in(creds) or is_authorized(request.authorization, creds):
            return None
        if _wants_page():
            return redirect(url_for("staff_login", next=request.full_path.rstrip("?")))
        return _challenge()

    @app.route("/login", methods=["GET", "POST"])
    def staff_login():
        creds = staff_credentials()
        next_url = _safe_next(request.values.get("next"))
        if creds is None or _signed_in(creds):
            return redirect(next_url)
        error = None
        username = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            if credentials_ok(username, request.form.get("password") or "", creds):
                session.clear()
                session.permanent = True
                session[SESSION_KEY] = _session_marker(creds)
                return redirect(next_url)
            time.sleep(1)  # slow down password guessing
            error = "That username and password didn't match."
        resp = Response(render_template("login.html", error=error, next_url=next_url, username=username),
                        status=401 if error else 200)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/logout", methods=["GET", "POST"])
    def staff_logout():
        session.clear()
        return redirect(url_for("staff_login"))
