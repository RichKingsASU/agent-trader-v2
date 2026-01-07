FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PORT=8080

# Build fingerprint (baked into image; can be overridden at deploy-time).
ARG GIT_SHA=unknown
ARG BUILD_ID=unknown
ARG BUILD_TIME_UTC=unknown
ARG IMAGE_REF=unknown
ENV GIT_SHA=$GIT_SHA \
    BUILD_ID=$BUILD_ID \
    BUILD_TIME_UTC=$BUILD_TIME_UTC \
    IMAGE_REF=$IMAGE_REF

# Create an unprivileged user for runtime.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

# Install Python deps first to maximize layer caching.
COPY backend/strategy_service/requirements.txt /app/backend/strategy_service/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/strategy_service/requirements.txt

# Copy the repo after dependencies.
COPY . /app

# Ensure the unprivileged user can read the app.
RUN chown -R appuser:appuser /app
USER 10001

EXPOSE 8080

CMD ["uvicorn", "backend.strategy_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
