FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/cloudrun_consumer

WORKDIR /app

# Install service dependencies first for better layer caching.
COPY cloudrun_consumer/requirements.txt /app/cloudrun_consumer/requirements.txt
RUN pip install --no-cache-dir -r /app/cloudrun_consumer/requirements.txt

# Copy repo (includes shared backend logging helpers).
COPY . /app

WORKDIR /app/cloudrun_consumer

ENV PORT=8080
EXPOSE 8080

CMD ["python","main.py"]

