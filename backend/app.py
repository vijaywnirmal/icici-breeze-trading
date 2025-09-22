from dotenv import load_dotenv
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from typing import Optional

from .utils.config import settings
from .utils.ssl_config import configure_ssl_context
from .middleware.rate_limit import RateLimitMiddleware
from .routes.login import router as login_router
from .routes.home import router as home_router
from .routes.stream import router as stream_router
from .routes.quotes import router as quotes_router
from .routes.backtests import router as backtests_router
from .routes.strategies import router as strategies_router
from .routes.historical import router as historical_router
from .routes.instruments import router as instruments_router
from .routes.nse_indexes import router as nse_indexes_router
from .routes.bulk_websocket import router as bulk_websocket_router
from .routes.option_chain import router as option_chain_router
from .utils.instruments_scheduler import DailyInstrumentsUpdater
from .utils.session import get_breeze, is_session_valid


# Load environment variables from .env at startup
load_dotenv()

# Configure SSL context to handle handshake failures
configure_ssl_context()

# Configure logging: keep access logs quiet, preserve important startup/error logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(title=settings.app_name)


# Enable CORS for simple static frontend usage
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    calls_per_hour=1000,  # 1000 requests per hour
    calls_per_minute=100  # 100 requests per minute
)


# Include route modules
app.include_router(login_router)
app.include_router(home_router)
# websocket router added without prefix
app.include_router(stream_router)
# removed watchlist routes per request
app.include_router(quotes_router)
app.include_router(backtests_router)
app.include_router(strategies_router)
app.include_router(historical_router)
app.include_router(instruments_router)
app.include_router(nse_indexes_router)
app.include_router(bulk_websocket_router)
app.include_router(option_chain_router)


updater: Optional[DailyInstrumentsUpdater] = None


@app.on_event("startup")
async def _startup() -> None:
    global updater
    # Check for critical env vars
    if not os.getenv("APP_NAME"):
        logging.warning("Critical environment variable APP_NAME is missing.")
    # Removed file-based session bootstrap to avoid relying on tracked files
    # Start instruments updater
    try:
        updater = DailyInstrumentsUpdater()
        await updater.start()
    except Exception as e:
        logging.error(f"Error starting DailyInstrumentsUpdater: {e}")
        updater = None


@app.on_event("shutdown")
async def _shutdown() -> None:
    global updater
    if updater is not None:
        try:
            await updater.stop()
        except Exception as e:
            logging.error(f"Error stopping DailyInstrumentsUpdater: {e}")


@app.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.environment,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)



