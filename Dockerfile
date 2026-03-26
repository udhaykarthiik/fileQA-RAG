FROM python:3.11-slim

WORKDIR /app

# Memory + Python optimizations
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RENDER=true
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
# fastembed downloads models to this cache dir at first run
ENV FASTEMBED_CACHE_PATH=/tmp/fastembed_cache

# Only gcc needed — no extra bloat
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model during build so it doesn't happen at runtime
# This keeps startup fast and avoids network calls on Render
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /tmp/uploads /tmp/vector_store /tmp/fastembed_cache

EXPOSE 10000

# Changes from original:
# - Removed --max-requests (was causing intentional restarts every 100 requests)
# - Added --preload (loads app once before forking, saves RAM)
# - Increased --threads 1->2 (handles concurrent requests without extra workers)
# - Reduced --timeout 600->120 (600s masked hung workers)
CMD gunicorn \
    --workers=1 \
    --threads=2 \
    --timeout=120 \
    --keep-alive=5 \
    --preload \
    --bind=0.0.0.0:10000 \
    backend.app:app