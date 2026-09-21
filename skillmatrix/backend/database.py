"""
Database connection layer + a minimal auth guard.

Read endpoints (GET) stay fully public -- anyone with the URL can view the
matrix and dashboard, no login needed. Write endpoints (POST/PUT/DELETE)
require a single shared admin token, sent as a header:
    Authorization: Bearer <ADMIN_TOKEN>
Set ADMIN_TOKEN as an environment variable on your host. This is a simple
single-user model (you are the one editor) -- swap in real per-user auth
later if more than one person needs edit access.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from fastapi import Header, HTTPException

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./skillmatrix.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")  # required in production; see require_admin()

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a request-scoped DB session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(authorization: str = Header(default=None)):
    """FastAPI dependency for every write endpoint. Compares the bearer token
    against ADMIN_TOKEN. If ADMIN_TOKEN isn't set on the host, writes are
    blocked entirely (fail closed) rather than silently left open."""
    if not ADMIN_TOKEN:
        raise HTTPException(500, "Server misconfigured: ADMIN_TOKEN is not set.")
    if not authorization or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "Missing or invalid admin token.")
    return True
