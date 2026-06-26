import logging
from fastapi import FastAPI
from app.core.config import settings

from app.api.routes import projects, jobs, auth

# Setup Basic Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production backend for Video Analyzer using Nemotron and OpenRouter",
    version="1.0.0"
)

# Configure CORS
origins = [
    "http://localhost:5173",  # Vite dev server
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {"status": "ok", "project": settings.PROJECT_NAME}

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])

@app.on_event("startup")
async def startup_event():
    logger.info("Running startup cleanup tasks...")
    # 1. Clean up stuck jobs in DB
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE analysis_jobs SET status = 'FAILED', error_message = 'Job failed due to server restart' WHERE status IN ('PENDING', 'RUNNING')"))
            await db.commit()
        logger.info("Successfully cleaned up stuck jobs in DB.")
    except Exception as e:
        logger.error(f"Failed to clean up stuck jobs: {e}")
        
    # 2. Purge Celery Queue to prevent ghost restarts
    try:
        import subprocess
        import sys
        # Use the same python executable environment to run celery purge
        subprocess.run([sys.executable, "-m", "celery", "-A", "app.core.celery_app", "purge", "-f"], check=False)
        logger.info("Successfully purged Celery queue.")
    except Exception as e:
        logger.error(f"Failed to purge celery queue: {e}")
