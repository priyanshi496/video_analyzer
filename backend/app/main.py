import logging
from fastapi import FastAPI
from app.core.config import settings

from app.api.routes import projects, jobs

# Setup Basic Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production backend for Video Analyzer using Nemotron and OpenRouter",
    version="1.0.0"
)

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {"status": "ok", "project": settings.PROJECT_NAME}

app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
