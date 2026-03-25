# Use Python 3.11 official image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RENDER=true

# Install system dependencies needed for Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create necessary directories
RUN mkdir -p uploads vector_store database

# Expose the port
EXPOSE 10000

# Run the application with gunicorn - use shell form for $PORT expansion
CMD gunicorn --workers=1 --threads=2 --timeout=300 --bind=0.0.0.0:$PORT backend.app:app