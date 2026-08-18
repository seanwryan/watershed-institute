"""
Mechanical classification of Flask mutating HTTP routes.

Every endpoint supporting POST, PUT, PATCH, or DELETE must belong to exactly one of:
  - WRITE_ENDPOINTS (PostgreSQL mutators; blocked when READ_ONLY_MODE)
  - PREVIEW_POST_ENDPOINTS (workbook preview uploads; no DB writes)
  - FRAMEWORK_ENDPOINTS (non-application; none currently)
"""
from __future__ import annotations

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Flask/Werkzeug built-ins that are not application write routes.
FRAMEWORK_ENDPOINTS = frozenset({"static"})


def mutating_routes(app):
    """Return sorted list of (endpoint, methods, rule) for mutating application routes."""
    found = []
    for rule in app.url_map.iter_rules():
        methods = rule.methods & MUTATING_METHODS
        if not methods:
            continue
        if rule.endpoint in FRAMEWORK_ENDPOINTS:
            continue
        found.append((rule.endpoint, frozenset(methods), rule.rule))
    return sorted(found, key=lambda x: (x[0], x[2]))


def verify_route_classification(app):
    """
    Raise AssertionError if any mutating route is unclassified or double-classified.
    Returns the mechanically discovered route list on success.
    """
    from dashboard.public_demo import STAFF_ONLY_ENDPOINTS
    from dashboard.read_only import PREVIEW_POST_ENDPOINTS, WRITE_ENDPOINTS

    overlap = WRITE_ENDPOINTS & PREVIEW_POST_ENDPOINTS
    if overlap:
        raise AssertionError(f"Endpoint(s) in both WRITE and PREVIEW: {sorted(overlap)}")

    routes = mutating_routes(app)
    unclassified = []
    for endpoint, methods, rule in routes:
        if endpoint in WRITE_ENDPOINTS or endpoint in PREVIEW_POST_ENDPOINTS:
            continue
        unclassified.append((endpoint, sorted(methods), rule))

    if unclassified:
        lines = [f"  {ep} {methods} {rule}" for ep, methods, rule in unclassified]
        raise AssertionError(
            "Unclassified mutating route(s):\n" + "\n".join(lines)
        )

    registered_writes = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.methods & MUTATING_METHODS and rule.endpoint in WRITE_ENDPOINTS
    }
    missing_writes = WRITE_ENDPOINTS - registered_writes
    if missing_writes:
        raise AssertionError(f"WRITE_ENDPOINTS not on app: {sorted(missing_writes)}")

    return routes
