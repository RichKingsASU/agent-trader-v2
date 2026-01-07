FROM python:3.12.8-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Harden: minimal OS packages + non-root user.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY backend/execution_agent/requirements.txt /app/backend/execution_agent/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/execution_agent/requirements.txt

COPY . /app

RUN chown -R appuser:appuser /app
USER 10001

CMD ["python", "-m", "backend.execution_agent.main"]

