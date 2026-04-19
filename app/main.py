import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.api.auth_routes import router as auth_router
from app.api.decision_routes import router as decision_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.student_routes import router as student_router
from app.api.trust_routes import router as trust_router
from app.api.routes import router as transcript_router
from app.api.workflow_routes import router as workflow_router
from app.core.config import settings
from app.db import run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="API for structured transcript extraction with heuristic controls, Textract fallback, and Bedrock normalization.",
)

allow_origins = settings.cors_allowed_origins
if settings.app_env.lower() in {"dev", "local", "development"} or not allow_origins or "*" in allow_origins:
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled request error path=%s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.on_event("startup")
def startup() -> None:
    run_migrations()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


app.include_router(auth_router)
app.include_router(decision_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(student_router, prefix="/api/v1")
app.include_router(trust_router, prefix="/api/v1")
app.include_router(transcript_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
