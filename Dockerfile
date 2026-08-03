# ==============================================================================
# Dockerfile
#
# Production-ready, secure multi-stage Dockerfile for FastAPI Photographer CRM.
# Decouples build-time compile tools from the runtime layer to produce small,
# secure, and optimized container images. Runs under a non-root user context.
# ==============================================================================

# --- Stage 1: Build Dependencies ---
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build essentials for potential source-distribution compile steps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy packages manifest and install into a clean prefix directory
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --- Stage 2: Runtime Image ---
FROM python:3.13-slim AS runner

# Configure Python runtime parameters:
# - PYTHONDONTWRITEBYTECODE: Prevents creation of transient .pyc cache files.
# - PYTHONUNBUFFERED: Ensures standard output stream is sent directly to logs.
# - PYTHONPATH: Tells Python to search for modules inside the application directory.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Create a secure, non-privileged system user and group (UID/GID 10001)
# to execute the web process, mitigating host compromise risks.
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -d /app -s /sbin/nologin -c "Application User" appuser

# Copy pre-installed dependency packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source files, assigning ownership to appuser
COPY --chown=appuser:appuser . .

# Switch container process execution context to the secure non-root user
USER appuser

# Expose the port Uvicorn listens on
EXPOSE 8000

# Launch Uvicorn server in production mode
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
