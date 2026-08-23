"""Fathom FastAPI application entry point.

Starts the server, configures CORS, includes routers, and creates
database tables on startup.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import Base, engine
from app.routers.evaluations import router as eval_router
from app.routers.ingest import router as ingest_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    On startup:
    - Enable pgvector extension
    - Create all database tables if they don't exist
    """
    async with engine.begin() as conn:
        # Enable pgvector extension (safe to call multiple times)
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create tables
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables ready")

    yield  # App is running

    # Shutdown: dispose engine connection pool
    await engine.dispose()
    print("🛑 Database connections closed")


# ──────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────

app = FastAPI(
    title="Fathom",
    description="Causal Tracing & Visual Debugging Infrastructure for Multi-Step AI Agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ingest_router)
app.include_router(eval_router)


@app.get("/", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Fathom",
        "version": "0.1.0",
    }


@app.get("/api/v1/health", tags=["Health"])
async def api_health():
    """API health check."""
    return {"status": "ok"}
