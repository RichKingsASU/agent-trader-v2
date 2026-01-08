# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables for production
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Copy and install dependencies
COPY cloudrun_ingestor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY cloudrun_ingestor/main.py /app/main.py

# Start the Gunicorn server
# - 1 worker, 1 thread for predictable, single-threaded background work
# - timeout 0 to prevent workers from being killed during long sleeps
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "1", "--timeout", "0", "main:app"]
