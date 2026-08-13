"""ETL config: DB URL and data paths. Use env or .env for secrets."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

DATA_DIR = Path(os.getenv("STREAMWATCH_DATA_DIR", "data"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/streamwatch")

# Optional: override individual file paths
SITES_FILE = Path(os.getenv("SITES_FILE", DATA_DIR / "2025 StreamWatch Locations.xlsx"))
VOLUNTEER_FILE = Path(os.getenv("VOLUNTEER_FILE", DATA_DIR / "Volunteer_Tracking.xlsm"))
EQUIPMENT_FILE = Path(os.getenv("EQUIPMENT_FILE", DATA_DIR / "CAT Meter Tracking v.1.xlsx"))

# Comma-separated DB names that destructive/rebuild migrations must refuse.
# Default protects the local archive name used during Phase 1 reconstruction.
# Add hosted production DB names via STREAMWATCH_PROTECTED_DBS when needed.
_DEFAULT_PROTECTED_DBS = "streamwatch_final"


def database_name_from_url(url: Optional[str] = None) -> Optional[str]:
    """Return the database name from a PostgreSQL URL, or None if unparseable."""
    raw = (url if url is not None else DATABASE_URL) or ""
    raw = raw.strip().strip("'\"").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        path = unquote(parsed.path or "").lstrip("/")
        if not path:
            return None
        name = path.split("/")[0].split("?")[0].strip()
        return name or None
    except Exception:
        return None


def protected_database_names() -> set:
    raw = os.getenv("STREAMWATCH_PROTECTED_DBS", _DEFAULT_PROTECTED_DBS)
    return {n.strip() for n in raw.split(",") if n.strip()}


def refuse_if_protected_database(url: Optional[str] = None) -> None:
    """
    Exit if DATABASE_URL targets a protected database name.

    Intended for migrations that rewrite result data. Override the protect list
    with STREAMWATCH_PROTECTED_DBS (comma-separated names).
    """
    name = database_name_from_url(url)
    if name and name in protected_database_names():
        print(
            f"Refusing to run against protected database {name!r}. "
            "Point DATABASE_URL at a writable target (e.g. streamwatch_demo), "
            "or adjust STREAMWATCH_PROTECTED_DBS deliberately."
        )
        sys.exit(2)


def safe_db_slug(url: Optional[str] = None) -> str:
    """Filesystem-safe slug from the database name (for report filenames)."""
    name = database_name_from_url(url) or "streamwatch"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return slug or "streamwatch"
