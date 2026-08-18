"""
Environment-controlled read-only mode for public demo deployments.

Set READ_ONLY_MODE=true (also 1, yes, on) to block PostgreSQL-changing web routes
while keeping browse, reports, exports, and workbook preview workflows available.
"""
import os
from functools import wraps

from flask import jsonify, render_template, request


# Flask endpoint names for routes that mutate PostgreSQL via the web app (20 total).
WRITE_ENDPOINTS = frozenset(
    {
        "site_new",
        "site_edit",
        "visit_new",
        "visit_edit",
        "chemical_new",
        "chemical_edit",
        "bacteria_new",
        "bacteria_edit",
        "habitat_new",
        "habitat_edit",
        "taxon_new",
        "taxon_edit",
        "taxon_delete",
        "meter_test_new",
        "volunteer_new",
        "volunteer_edit",
        "volunteer_assignment_new",
        "volunteer_assignment_edit",
        "training_session_new",
        "volunteer_training_new",
    }
)

# POST upload routes that only read workbooks and write ephemeral preview files.
PREVIEW_POST_ENDPOINTS = frozenset(
    {
        "imports_hab_preview_post",
        "imports_bact_preview_post",
        "report_bact_preview_post",
    }
)

_READ_ONLY_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_read_only_mode() -> bool:
    """True when READ_ONLY_MODE is set to a truthy value."""
    return (os.getenv("READ_ONLY_MODE") or "").strip().lower() in _READ_ONLY_TRUTHY


def _wants_json() -> bool:
    if request.path.startswith("/api/"):
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def read_only_response(*, blocked_form: bool):
    """Return 403 with a friendly read-only message."""
    message = "This public demo is read-only. Data entry and editing are disabled."
    if _wants_json():
        return jsonify({"error": message}), 403
    return (
        render_template(
            "read_only_blocked.html",
            message=message,
            blocked_form=blocked_form,
        ),
        403,
    )


def register_read_only(app):
    """Attach context processor and before_request enforcement to the Flask app."""

    @app.context_processor
    def _inject_read_only():
        return {"read_only_mode": is_read_only_mode()}

    @app.before_request
    def _enforce_read_only():
        if not is_read_only_mode():
            return None
        endpoint = request.endpoint
        if endpoint is None or endpoint in PREVIEW_POST_ENDPOINTS:
            return None
        if endpoint not in WRITE_ENDPOINTS:
            return None
        if request.method == "POST":
            return read_only_response(blocked_form=False)
        if request.method in ("GET", "HEAD"):
            return read_only_response(blocked_form=True)
        return read_only_response(blocked_form=False)


def require_writable(f):
    """Optional route decorator; before_request is the primary enforcement."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        if is_read_only_mode():
            return read_only_response(blocked_form=request.method != "POST")
        return f(*args, **kwargs)

    return wrapped
