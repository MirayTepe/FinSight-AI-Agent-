#!/usr/bin/env bash
set -e

# Backend FastAPI sunucusunu arka planda başlat (8000 portu)
echo "[FinSight] Starting FastAPI backend on port 8000..."
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 &

# Streamlit ön yüzünü başlat (8501 portu veya bulut sağlayıcısının verdiği $PORT)
TARGET_PORT=${PORT:-8501}
echo "[FinSight] Starting Streamlit frontend on port $TARGET_PORT..."
exec streamlit run app.py \
    --server.port=$TARGET_PORT \
    --server.address=0.0.0.0 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false

