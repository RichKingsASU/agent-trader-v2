FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PORT=8080

# Create an unprivileged user for runtime.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

# Install deps first for better caching.
COPY backend/risk_service/requirements.lock /app/backend/risk_service/requirements.lock
RUN python -m pip install --no-cache-dir -r /app/backend/risk_service/requirements.lock

COPY . .

EXPOSE 8080

CMD ["uvicorn", "backend.risk_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
