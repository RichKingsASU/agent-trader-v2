# Basic Python Dockerfile for strategy-whale
FROM python:3.12-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt || true

CMD ["bash", "-lc", "echo 'Entrypoint not set for strategy-whale'"]
