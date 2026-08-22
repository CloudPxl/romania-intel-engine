from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "raw_pdfs"
DB_PATH = DATA_DIR / "intel_local.db"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    APP_NAME: str = "RomaniaIntelEngine"
    ENV: str = "development"
    SQLITE_DB_PATH: Path = DB_PATH
    PDF_STORAGE_PATH: Path = PDF_DIR
    
    # HTTP Client Configuration
    REQUEST_TIMEOUT_SECONDS: float = 30.0
    MAX_RETRIES: int = 3
    DEFAULT_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    DEFAULT_HEADERS: dict = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
