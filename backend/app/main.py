from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy import text

from app.admin_routes import router as admin_router
from app.agent_routes import router as agent_router
from app.approval_routes import router as approval_router
from app.browser_agent import close_all_sessions
from app.browser_routes import router as browser_router
from app.form_execution_routes import router as e2e_router
from app.form_mapping_routes import router as form_mapping_router
from app.knowledge_routes import router as knowledge_router
from app.live_browser_routes import router as live_browser_router
from app.orchestrator_routes import router as orchestrator_router
from app.orchestrator_screenshot_route import router as orchestrator_screenshot_router
from app.routes import router
from app.security import validate_production_security
from app.config import settings
from app.database import Base, engine
from app import db_models  # noqa: F401
from app.payment_routes import router as payment_router
from app.universal_research_routes import router as universal_research_router
from app.auth_routes import router as auth_router
from app.task_routes import router as task_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_security()
    # Alembic is the production schema authority. Keep create_all only for
    # local development and tests; production startup must not mutate schema.
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)
    yield
    await close_all_sessions()


app = FastAPI(
    title="Formwise Agent API",
    version="0.1.0",
    description="Secure profile, document-vault, knowledge, agent planning, controlled browser, universal form discovery, field mapping, approval safety, end-to-end form execution, research-driven orchestration and zero-trust live browser sessions.",
    lifespan=lifespan,
)


@app.middleware("http")
async def production_request_guard(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
    content_length = int(request.headers.get("content-length", "0") or 0)
    if content_length > settings.api_request_size_limit_bytes:
        return JSONResponse(status_code=413, content={"detail": "request body is too large", "correlation_id": correlation_id}, headers={"X-Correlation-ID": correlation_id})
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-ID", "X-Razorpay-Signature", "X-Razorpay-Event-Id"],
)
app.include_router(router)
app.include_router(knowledge_router)
app.include_router(agent_router)
app.include_router(browser_router)
app.include_router(live_browser_router)
app.include_router(form_mapping_router)
app.include_router(approval_router)
app.include_router(e2e_router)
app.include_router(orchestrator_router)
app.include_router(orchestrator_screenshot_router)
app.include_router(universal_research_router)
app.include_router(auth_router)
app.include_router(payment_router)
app.include_router(admin_router)
app.include_router(task_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "formwise-api"}


@app.get("/ready", tags=["system"])
async def readiness() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        client = Redis.from_url(settings.redis_url, username=settings.redis_username or None, password=settings.redis_password or None, ssl=settings.redis_tls or settings.redis_url.startswith("rediss://"), socket_timeout=settings.redis_socket_timeout_seconds)
        client.ping()
        client.close()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    return {"status": "ok" if all(value == "ok" for value in checks.values()) else "degraded", **checks}
