# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables for production
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PYTHONPATH=/app:$PYTHONPATH

WORKDIR /app

# Copy and install dependencies
COPY cloudrun_ingestor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
# Copy the entrypoint
COPY cloudrun_ingestor/main.py ./main.py
COPY cloudrun_ingestor/gunicorn_conf.py ./gunicorn_conf.py

# Start the Gunicorn server
# - 1 worker, 1 thread for predictable, single-threaded background work
# - timeout 0 to prevent workers from being killed during long sleeps
CMD ["gunicorn", "--config", "gunicorn_conf.py", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "1", "--timeout", "0", "main:app"]
