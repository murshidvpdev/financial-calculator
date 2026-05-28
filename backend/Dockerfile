# =============================================================================
# FINANCE CALCULATOR — Multi-Stage Dockerfile
# =============================================================================
#
# What is a multi-stage build?
# ─────────────────────────────
# A single Dockerfile with multiple FROM statements.
# Each FROM starts a fresh layer; you only COPY what you need into the final image.
#
# Stage 1 (builder): Has all build tools (pip, gcc, compilers)
#   → Installs Python dependencies into a virtual env
#   → Build tools NOT included in final image (security + size)
#
# Stage 2 (runtime): Minimal image, just what the app needs to RUN
#   → Only copies the installed packages from the builder stage
#   → Resulting image is much smaller and has a smaller attack surface
#
# Without multi-stage: 1.2GB+ image (pip, gcc, build headers, dev tools)
# With multi-stage:    ~200MB image (just Python + your packages)
#
# Why does image size matter?
#   - Smaller = faster to pull from ECR → faster deployments
#   - Smaller = less storage cost in ECR (pay per GB)
#   - Smaller attack surface → fewer vulnerabilities from unused tools
#
# Interview: "We use multi-stage builds to separate the build environment
# from the runtime environment. The builder stage installs dependencies with
# all the necessary build tools. The runtime stage copies only the installed
# packages — no build tools, no pip, no compilers. This gives us a lean,
# secure production image."
#
# Build:  docker build -t finance-app:latest .
# Run:    docker run -p 8000:8000 --env-file .env finance-app:latest
# =============================================================================


# =============================================================================
# STAGE 1 — BUILDER
# Installs all dependencies into a virtual environment.
# This stage has pip and build tools — NOT included in the final image.
# =============================================================================
FROM python:3.13-slim AS builder

# Why python:3.13-slim?
#   - "slim" = no compilers, no X11, no docs → smaller base (about 50MB)
#   - Still has enough for most pure-Python and C-extension packages
#   - "alpine" would be even smaller but breaks many C-extension packages
#     (musl libc vs glibc = compatibility issues with asyncpg, bcrypt, etc.)

# ── System build dependencies ─────────────────────────────────────────────────
# libpq-dev: PostgreSQL client headers (needed to compile asyncpg/psycopg2)
# gcc:       C compiler (needed for bcrypt and asyncpg native extensions)
# curl:      Needed to download pip if required

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Python virtual environment ────────────────────────────────────────────────
# We create a venv at a well-known path (/opt/venv).
# The runtime stage will copy this directory.
# Why a venv inside Docker? It makes COPY easier — one directory for all packages.

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# ── Install Python dependencies ───────────────────────────────────────────────
# Why copy requirements.txt first (before copying app code)?
#   Docker layer caching! If requirements.txt hasn't changed, this layer
#   is served from cache — no re-download needed. Much faster CI/CD.
#   If we copied ALL files first, any code change would invalidate this layer.
#
# This is the most important Dockerfile optimization: copy dependency files
# BEFORE the source code, so package installation is cached separately.

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# =============================================================================
# STAGE 2 — RUNTIME
# The final image. Only contains what the app needs to RUN.
# No pip, no gcc, no build headers — minimal attack surface.
# =============================================================================
FROM python:3.13-slim AS runtime

# ── Metadata labels ───────────────────────────────────────────────────────────
# OCI (Open Container Initiative) standard labels.
# Visible in: docker inspect, ECR console, vulnerability scanners.
LABEL maintainer="murshidveypey790@gmail.com"
LABEL org.opencontainers.image.title="Finance Calculator"
LABEL org.opencontainers.image.description="Production-grade Finance & Expense Tracker API"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="https://github.com/murshi/finance-calculator"

# ── System runtime dependencies ───────────────────────────────────────────────
# libpq5: PostgreSQL client library (asyncpg needs this at RUNTIME, not just build)
# curl:   Needed for health check commands in orchestration

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Copy installed packages from builder ─────────────────────────────────────
# This is the key multi-stage trick: we copy the INSTALLED venv, not pip itself
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv

# ── Non-root user ─────────────────────────────────────────────────────────────
# Running as root in a container is a security risk.
# If an attacker gets RCE (Remote Code Execution), they'd have root access
# inside the container — and potentially to the host via escape vulnerabilities.
#
# Best practice: create a dedicated user with no special privileges.
# uid=1001 is conventionally used for "app" users in containers.

RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Copy application source ───────────────────────────────────────────────────
# Copy everything the app needs to run.
# .dockerignore excludes: .venv, __pycache__, tests, .git, etc.

COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup templates/ ./templates/
COPY --chown=appuser:appgroup static/ ./static/
COPY --chown=appuser:appgroup alembic.ini ./
COPY --chown=appuser:appgroup migrations/ ./migrations/

# ── Switch to non-root user ────────────────────────────────────────────────────
# Everything from here on runs as appuser, not root
USER appuser

# ── Environment defaults ──────────────────────────────────────────────────────
# These are defaults — override with --env or --env-file at runtime.
# NEVER bake secrets into the image! Use secrets management (AWS Secrets Manager).

ENV PYTHONUNBUFFERED=1
# PYTHONUNBUFFERED: Print stdout/stderr immediately (no buffering)
# Without this, print() output may be delayed → logs appear after crashes

ENV PYTHONDONTWRITEBYTECODE=1
# Don't write .pyc files — saves disk space in containers

ENV PYTHONPATH=/app
# Ensure Python can find our 'app' module from /app/

ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=2

# ── Health check ─────────────────────────────────────────────────────────────
# Docker health checks let the orchestrator (ECS, Kubernetes) know if
# the app is ready to receive traffic. If the check fails repeatedly,
# the container is marked unhealthy and traffic is redirected to healthy instances.
#
# interval: How often to run the check (30s)
# timeout:  Consider unhealthy if check takes > 5s
# retries:  After 3 failures, mark as unhealthy
# start-period: Give the app 40s to start up before health checks begin

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:${PORT}/api/v1/health/live || exit 1

# ── Expose port ───────────────────────────────────────────────────────────────
# EXPOSE is documentation only — it doesn't actually publish the port.
# The actual port mapping happens at runtime: docker run -p 8000:8000
EXPOSE 8000

# ── Startup command ───────────────────────────────────────────────────────────
# Use exec form (JSON array) NOT shell form.
# Shell form: CMD uvicorn app.main:app ...   (runs as /bin/sh -c "uvicorn ...")
# Exec form:  CMD ["uvicorn", "app.main:app"] (uvicorn IS PID 1)
#
# Why does PID 1 matter?
#   PID 1 receives SIGTERM from Docker on container stop.
#   Shell form wraps in /bin/sh which may not forward SIGTERM to uvicorn.
#   Exec form: uvicorn receives SIGTERM directly → graceful shutdown.

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT} --workers ${WORKERS}"]

# =============================================================================
# PRODUCTION NOTES
# =============================================================================
# For production, consider:
#
# 1. Use gunicorn as the process manager:
#    CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker"]
#    Gunicorn handles worker management, graceful restarts, etc.
#
# 2. Run database migrations before starting:
#    CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app ..."]
#    Or run migrations as a separate "init container" in Kubernetes.
#
# 3. Never run as root in production containers.
#    Our non-root user (appuser) is already set up above.
#
# 4. Pin base image versions for reproducibility:
#    Use python:3.13.3-slim (exact version) not python:3.13-slim (floating tag)
# =============================================================================
