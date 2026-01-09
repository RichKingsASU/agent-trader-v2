FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

COPY cloudrun_consumer/requirements.txt ./cloudrun_consumer/requirements.txt
RUN pip install --no-cache-dir -r ./cloudrun_consumer/requirements.txt

COPY . /app

EXPOSE 8080

CMD ["python","-m","cloudrun_consumer.main"]

