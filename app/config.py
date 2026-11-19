from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "platform.db"
FILES_DIR = DATA_DIR / "files"
SOURCES_DIR = DATA_DIR / "sources"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DATABASE_URL = "sqlite:///" + DB_PATH.resolve().as_posix()

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
SOURCES_DIR.mkdir(parents=True, exist_ok=True)
