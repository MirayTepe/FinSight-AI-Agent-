#!/usr/bin/env bash
set -e

python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 &

TARGET_PORT=${PORT:-8501}

exec streamlit run app.py \
    --server.port=$TARGET_PORT \
    --server.address=0.0.0.0 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false
