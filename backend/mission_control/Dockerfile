FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Minimal OS deps (CA certs for internal HTTP).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (matches other k8s manifests using 10001).
RUN useradd -u 10001 -m -s /usr/sbin/nologin appuser

WORKDIR /app

COPY backend/mission_control/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy only what's needed: backend package + static agents config
COPY backend /app/backend
COPY configs /app/configs

USER 10001

EXPOSE 8080

CMD ["uvicorn", "backend.mission_control.main:app", "--host", "0.0.0.0", "--port", "8080"]

