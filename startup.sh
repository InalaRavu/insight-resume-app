#!/bin/bash
set -e

echo "Starting FastAPI backend service on port 8000..."
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000 &

echo "Waiting for FastAPI to initialize..."
sleep 3

echo "Starting Streamlit UI on external port ${WEBSITES_PORT:-8080}..."
python -m streamlit run src/ui.py \
    --server.port ${WEBSITES_PORT:-8080} \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false