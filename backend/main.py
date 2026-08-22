import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from contextlib import asynccontextmanager
from backend.routes.reception import router as reception_router
from backend.routes.encounter import router as encounter_router
from backend.routes.events import router as events_router
from backend.db.local import init_db
from backend.pipeline.sync_poller import start_sync_poller, stop_sync_poller

# Initialize database schema on startup
init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background sync poller for offline store-and-forward
    start_sync_poller()
    # NOTE: Models (GLiNER, Whisper, Silero VAD) are loaded lazily on first use.
    # Preloading all at startup caused OOM kills on constrained edge hardware.
    yield
    # Stop the poller on shutdown
    stop_sync_poller()

app = FastAPI(
    title="MedSync API",
    description="Zero-Trust ABDM-Compliant Healthcare Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# ---------------------------------------------------------
# Security Middlewares
# ---------------------------------------------------------

# 1. CORS Configuration
# Allow local development frontend origins and configured FRONTEND_URL
FRONTEND_URL = os.getenv("FRONTEND_URL", "")
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:5173",
]
if FRONTEND_URL and FRONTEND_URL not in allowed_origins:
    allowed_origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Accept", "X-Role", "Authorization"],
)

# 2. Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent Clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Note: Content-Security-Policy is intentionally omitted from the API.
        # It is only meaningful on HTML document responses (the frontend's job).
        # Setting it on JSON API responses can block cross-origin fetch in some
        # browser configurations.
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------

app.include_router(reception_router)
app.include_router(encounter_router)
app.include_router(events_router)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "MedSync API is running securely."}
