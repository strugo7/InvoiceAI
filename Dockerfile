# syntax=docker/dockerfile:1
#
# InvoiceAI backend — production container image.
#
# Design notes (why it looks the way it does):
#   * Multi-stage: a "builder" compiles/installs deps into an isolated venv,
#     the final "runtime" stage carries only the venv + app — no compilers.
#   * Base is python:3.11-slim (Debian/glibc), NOT alpine: deps like
#     cryptography and python-bidi ship glibc manylinux wheels but have no
#     musl wheels, so alpine would compile them from source (Rust toolchain,
#     slow, fragile). slim builds faster and more reliably.
#   * Runs as a non-root user with a venv on PATH and tini as PID 1.
#   * Pin the base by digest in production for reproducibility, e.g.
#       FROM python:3.11-slim-bookworm@sha256:<digest> AS builder
#     (left on the floating tag here so you can pull updates during dev).

ARG PYTHON_IMAGE=python:3.11-slim-bookworm

# ──────────────────────────────────────────────────────────────────────────
# Stage 1 — builder: resolve and install Python dependencies into a venv
# ──────────────────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build toolchain — only present in this throwaway stage, never in runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Self-contained virtualenv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# requirements first → this layer (the slow one) is cached until deps change.
COPY backend/requirements.txt .
# BuildKit cache mount keeps the pip download cache across rebuilds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime: minimal image that actually ships
# ──────────────────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime

# OCI metadata — populated by CI (docker build --build-arg VCS_REF=$(git rev-parse HEAD) ...)
ARG VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="InvoiceAI Backend" \
      org.opencontainers.image.description="Gmail invoice tracker — FastAPI + Gemini" \
      org.opencontainers.image.source="https://github.com/strugo7/InvoiceAI" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    FRONTEND_DIR=/app/static \
    PORT=8000

# tini = tiny PID-1 init: reaps zombies and forwards SIGTERM for graceful
# shutdown (important for K8s rolling updates).
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root, no shell, fixed UID/GID (matches a K8s runAsUser: 1000).
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Carry over the fully-built virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# App code last (changes most often). --chown avoids a second recursive chown
# layer and makes /app writable by appuser (invoices.json, reports/, ...).
COPY --chown=appuser:appuser backend/ .
COPY --chown=appuser:appuser frontend/ ./static/

USER appuser

EXPOSE 8000

# Local/Compose health signal. NOTE: Kubernetes ignores this and uses its own
# liveness/readiness probes instead — define those in the Deployment manifest.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "server.py"]
