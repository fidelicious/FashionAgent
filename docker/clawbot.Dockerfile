# ─────────────────────────────────────────────────────────────────────────────
# Clawbot runtime image
#
# What this image contains:
#   - Python 3.12 (slim)
#   - System libraries needed by rembg/Pillow/Tesseract
#   - The clawbot package, installed editable
#
# What it does NOT contain:
#   - Ollama (separate container)
#   - Application data (mounted from ~/clawbot/{db,images,inbox,logs,backups})
#
# Build: docker compose build clawbot
# Run:   docker compose up -d clawbot
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base

# System deps:
#   - libgl1, libglib2.0-0, libsm6, libxext6, libxrender1: Pillow / OpenCV / rembg
#   - tesseract-ocr: OCR for retailer screenshots
#   - libjpeg, libpng, libtiff, libwebp: image format support
#   - tini: clean PID-1 signal handling
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libjpeg62-turbo \
        libpng16-16 \
        libtiff6 \
        libwebp7 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — clawbot reads/writes /data which is bind-mounted from ~/clawbot
RUN useradd --create-home --uid 1000 clawbot
WORKDIR /app

# Copy only metadata first for layer caching
COPY --chown=clawbot:clawbot pyproject.toml /app/
COPY --chown=clawbot:clawbot README.md /app/

# Install runtime + chosen optional groups. Image pipeline groups are heavy
# (~2 GB of torch wheels) — only install what V1 needs.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[vision,discord,scheduler,email,llm,api]"

# Copy source. Done late so code edits don't bust the dep-install cache.
COPY --chown=clawbot:clawbot src/ /app/src/

USER clawbot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CLAWBOT_HOME=/data

# All persistent state lives in /data, bind-mounted from ~/clawbot on the host
VOLUME ["/data"]

# Healthcheck — FastAPI exposes /healthz (built in step 13)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/healthz').raise_for_status()" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "clawbot.main"]
