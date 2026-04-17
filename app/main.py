import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as transcript_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    run_migrations()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


app.include_router(transcript_router, prefix="/api/v1")
