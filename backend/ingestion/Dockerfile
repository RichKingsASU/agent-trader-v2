FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install only the dependencies required for vm_ingest.
COPY backend/ingestion/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend package so `python -m backend.ingestion.vm_ingest` works.
COPY backend ./backend

ENTRYPOINT ["python", "-m", "backend.ingestion.vm_ingest"]

