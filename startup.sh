#!/bin/bash
set -e

# The backend binds to loopback ONLY. It trusts the Easy Auth principal headers
# forwarded by the Streamlit process, so it must never be reachable from outside
# the container -- the platform's authenticated edge is the only way in.
echo "Starting FastAPI backend service on 127.0.0.1:8000..."
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Stop the whole container if the backend dies, rather than serving a UI that
# cannot do anything.
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

# Wait for the backend to answer its health check before exposing the UI.
echo "Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null; then
        echo "Backend healthy."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "Backend failed to become healthy after 30s." >&2
        exit 1
    fi
    sleep 1
done

# Streamlit is the only publicly exposed port, and it sits behind Easy Auth.
# XSRF protection stays ON; disabling it was leaving the upload form open to
# cross-site POSTs from an authenticated browser session.
echo "Starting Streamlit frontend on port 8501..."
python -m streamlit run src/ui.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.enableCORS=true \
    --server.enableXsrfProtection=true \
    --server.maxUploadSize=10 \
    --browser.gatherUsageStats=false
