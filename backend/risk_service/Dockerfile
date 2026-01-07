FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PORT=8080

# Create an unprivileged user for runtime.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

# Install deps first for better caching.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY . .

EXPOSE 8080

RUN chown -R appuser:appuser /app
USER 10001

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health').read()" || exit 1

CMD ["uvicorn", "backend.risk_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
