from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv


# Ensure .env is loaded before reading environment variables
# Load both project root .env and backend/.env (backend overrides only missing keys)
backend_dir = Path(__file__).parent.parent
project_root = backend_dir.parent

# Load root .env first
load_dotenv(project_root / ".env")
# Then load backend/.env without overriding already-set variables
load_dotenv(backend_dir / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Automated Trading Platform")
    environment: str = os.getenv("ENVIRONMENT", "development")

    breeze_api_key: str | None = os.getenv("BREEZE_API_KEY")
    breeze_api_secret: str | None = os.getenv("BREEZE_API_SECRET")
    breeze_session_token: str | None = os.getenv("BREEZE_SESSION_TOKEN")

    # PostgreSQL DSN (e.g., postgresql+psycopg://user:pass@localhost:5432/dbname)
    postgres_dsn: str | None = os.getenv("POSTGRES_DSN")

    # Redis URL (e.g., redis://localhost:6379/0)
    redis_url: str | None = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Control whether to run instruments first-load automatically on login
    instruments_first_run_on_login: bool = os.getenv("INSTRUMENTS_FIRST_RUN_ON_LOGIN", "true").lower() in ("1", "true", "yes")


settings = Settings()


