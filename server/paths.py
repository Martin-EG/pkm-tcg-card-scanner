"""Where the server finds its files, relative to the repository root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "reglas.yaml"
# Catalog, images, indexes, SQLite, scans, certificates (git-ignored).
DATA = ROOT / "data"
# Scans, corrections, price cache, exchange rates, buy sessions.
DB_PATH = DATA / "scanner.db"
SCANS_DIR = DATA / "scans"
CA_CERT = DATA / "certs" / "ca.pem"
# Built phone app (cd app && npm run build).
APP_DIST = ROOT / "app" / "dist"
