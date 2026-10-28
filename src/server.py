"""
FinSight — FastAPI Sunucu

Web API endpoint'lerini ve dashboard sunucusunu barındırır.
Çalıştırma: uvicorn src.server:app --reload --port 8000
"""

from fastapi import FastAPI
from src.config import APP_ENV, DEBUG

app = FastAPI(
    title="FinSight AI Agent API",
    description="Halka açık şirket araştırma ve finansal analiz AI agent'ı",
    version="0.1.0",
    debug=DEBUG,
)


@app.get("/")
async def root():
    """Sağlık kontrolü endpoint'i."""
    return {
        "service": "FinSight AI Agent",
        "status": "running",
        "environment": APP_ENV,
    }


@app.get("/health")
async def health_check():
    """Detaylı sağlık kontrolü."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        # TODO: Agent ve tool durumları eklenecek (M2)
    }


# TODO: Agent endpoint'leri (M2 aşamasında geliştirilecek)
# @app.post("/api/analyze")
# @app.post("/api/compare")
# @app.get("/api/stock/{ticker}")
