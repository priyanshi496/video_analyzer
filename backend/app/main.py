import logging
from fastapi import FastAPI
from app.core.config import settings

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

# TODO: Include routers from app.api.routes
