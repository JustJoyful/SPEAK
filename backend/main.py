import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.routes.reception import router as reception_router
from backend.routes.encounter import router as encounter_router
from backend.db.local import init_db

# Initialize database schema on startup
init_db()

app = FastAPI(
    title="MedSync API",
    description="Zero-Trust ABDM-Compliant Healthcare Gateway",
    version="1.0.0"
)

# ---------------------------------------------------------
# Security Middlewares
# ---------------------------------------------------------

# 1. CORS Configuration
# For production, this should be restricted to the actual frontend origin
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"], # In production, restrict to X-Role, Content-Type, etc.
)

# 2. Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent Clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # XSS Protection (Legacy, but good for defense-in-depth)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Strict Transport Security (HSTS) - Assuming HTTPS in production
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Content Security Policy (Basic API configuration)
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------

app.include_router(reception_router)
app.include_router(encounter_router)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "MedSync API is running securely."}
