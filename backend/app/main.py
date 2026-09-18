from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_security()
    Base.metadata.create_all(bind=engine)
    yield
    await close_all_sessions()


app = FastAPI(
    title="Formwise Agent API",
    version="0.1.0",
    description="Secure profile, document-vault, knowledge, agent planning, controlled browser, universal form discovery, field mapping, approval safety, end-to-end form execution, research-driven orchestration and zero-trust live browser sessions.",
    lifespan=lifespan,
)
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "formwise-api"}
