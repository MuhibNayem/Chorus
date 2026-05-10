FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install git for workspace snapshots (Phase 1 rollback/recovery)
# Install curl for docker-compose healthchecks
# Install docker CLI so Celery workers can spawn verification containers (sandbox builds)
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-26.1.4.tgz | tar xz -C /tmp && \
    cp /tmp/docker/docker /usr/local/bin/docker && \
    rm -rf /tmp/docker

WORKDIR /app/backend

COPY pyproject.toml ./
COPY src ./src
COPY scripts ./scripts
RUN chmod +x scripts/*.sh

RUN for attempt in 1 2 3; do \
      pip install --no-cache-dir --retries 10 --timeout 120 . && exit 0; \
      echo "pip install failed on attempt ${attempt}, retrying..."; \
      sleep 5; \
    done; \
    exit 1

RUN mkdir -p /var/lib/deepseek/workspaces /var/lib/deepseek/checkpoints

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
