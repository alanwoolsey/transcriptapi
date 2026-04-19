from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def get_database_url() -> str | None:
    return settings.resolved_database_url


@lru_cache(maxsize=1)
def get_engine():
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("Database is not configured.")
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def get_db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
