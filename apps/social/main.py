"""
Social Media Module - Combined FB + Zalo + Instagram webhook handlers
Serves all social platforms on a single port
"""
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

# Import sub-apps
from apps.social.facebook import app as fb_app
from apps.social.zalo import app as zalo_app

logger = logging.getLogger(__name__)

# ──── Lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🤖 Starting Social Media Bot Module")
    yield
    logger.info("🛑 Shutting down Social Media Bot")


# ──---- Main App ----

app = FastAPI(
    title="Social Media Bot Module",
    description="Unified webhook handler for Facebook, Zalo, Instagram",
    version="0.1.0",
    lifespan=lifespan,
)


# ──---- Mount Sub-Apps ----

app.mount("/facebook", fb_app)
app.mount("/zalo", zalo_app)


# ──---- Health Check ----

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "social_bot_module",
        "platforms": ["facebook", "zalo"],
    }


@app.get("/")
async def root():
    return {
        "name": "Social Media Bot Module",
        "platforms": {
            "facebook": "POST /facebook/webhook",
            "zalo": "POST /zalo/webhook",
        },
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
    )
