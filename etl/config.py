"""ETL config: DB URL and data paths. Use env or .env for secrets."""
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("STREAMWATCH_DATA_DIR", "data"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/streamwatch")

# Optional: override individual file paths
SITES_FILE = Path(os.getenv("SITES_FILE", DATA_DIR / "2025 StreamWatch Locations.xlsx"))
VOLUNTEER_FILE = Path(os.getenv("VOLUNTEER_FILE", DATA_DIR / "Volunteer_Tracking.xlsm"))
EQUIPMENT_FILE = Path(os.getenv("EQUIPMENT_FILE", DATA_DIR / "CAT Meter Tracking v.1.xlsx"))
