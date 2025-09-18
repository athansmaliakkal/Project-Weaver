import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DB_DIR = BASE_DIR / "db"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "leads.db"

WEBHOOK_URL = os.getenv("DEFAULT_WEBHOOK_URL", "")
CONCURRENCY_LIMIT = int(os.getenv("CONCURRENCY_LIMIT", 3))
PROXY_SERVER = os.getenv("PROXY_SERVER", None)
