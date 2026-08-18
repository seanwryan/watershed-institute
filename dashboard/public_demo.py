"""
Environment-controlled public demo visibility boundary.

PUBLIC_DEMO_MODE=true hides Watershed staff-only operational areas (volunteers,
equipment, training/assignment reports, and related APIs) from public browsing.

This is separate from READ_ONLY_MODE, which controls PostgreSQL write blocking.
For a public portfolio deployment, set both to true.
"""
import os

from flask import jsonify, render_template, request

# Staff / operational endpoints blocked when PUBLIC_DEMO_MODE is enabled.
# Volunteer write routes remain in WRITE_ENDPOINTS (read_only.py) for write blocking.
STAFF_ONLY_ENDPOINTS = frozenset(
    {
        # Volunteers
        "volunteers_page",
        "volunteer_detail_page",
        "volunteer_new",
        "volunteer_edit",
        "volunteer_assignment_new",
        "volunteer_assignment_edit",
        "volunteer_training_new",
        "api_volunteers",
        "api_volunteer_detail",
        # Equipment / meter testing (read views)
        "equipment_page",
        "equipment_detail_page",
        "meter_test_new",
        "api_equipment",
        "api_equipment_detail",
        # Training sessions (read + create forms)
        "training_session_new",
        "training_detail_page",
        # Staff reports
        "report_training",
        "report_training_csv",
        "report_assignments",
        "report_assignments_csv",
    }
)

_READ_ONLY_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_public_demo_mode() -> bool:
    """True when PUBLIC_DEMO_MODE is set to a truthy value."""
    return (os.getenv("PUBLIC_DEMO_MODE") or "").strip().lower() in _READ_ONLY_TRUTHY


def _wants_json() -> bool:
    if request.path.startswith("/api/"):
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def public_demo_blocked_response():
    """Return 404 for staff-only content in public demo mode."""
    message = "This section is not available in the public demonstration."
    if _wants_json():
        return jsonify({"error": message}), 404
    return (
        render_template(
            "public_demo_blocked.html",
            message=message,
        ),
        404,
    )


def register_public_demo(app):
    """Attach context processor and before_request staff-only enforcement."""

    @app.context_processor
    def _inject_public_demo():
        return {"public_demo_mode": is_public_demo_mode()}

    @app.before_request
    def _enforce_public_demo():
        if not is_public_demo_mode():
            return None
        endpoint = request.endpoint
        if endpoint is None or endpoint not in STAFF_ONLY_ENDPOINTS:
            return None
        return public_demo_blocked_response()
