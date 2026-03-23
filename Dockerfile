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

# DEBUG: List the backend directory to verify files
RUN ls -la /app/backend/
RUN ls -la /app/backend/services/ || echo "Services directory not found!"

# Create necessary directories
RUN mkdir -p uploads vector_store database

# Expose the port
EXPOSE 5000

# Run the application with gunicorn
CMD ["gunicorn", "--workers=1", "--threads=2", "--timeout=300", "--bind=0.0.0.0:5000", "backend.app:app"]