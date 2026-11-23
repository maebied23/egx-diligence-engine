"""Paths and settings. Everything that touches documents stays under the project folder."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("EFE_ROOT", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"
RAW = DATA / "raw"            # downloaded filings (git-ignored)
DB_PATH = Path(os.environ.get("EFE_DB", DATA / "db" / "efe.sqlite"))  # git-ignored
SOURCES = DATA / "sources"
FILINGS_CSV = SOURCES / "filings.csv"

# A page with fewer extractable characters than this is treated as having no usable text layer.
MIN_TEXT_CHARS = 200
