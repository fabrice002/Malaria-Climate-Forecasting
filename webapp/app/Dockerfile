FROM python:3.12-slim

# System deps for psycopg / scientific stack
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Build context is webapp/ (see ../docker-compose.yml), so paths are relative to
# that directory — the app package and the model bundle sit side by side there.
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY deployment_bundle ./deployment_bundle

EXPOSE 8000

# Production: multiple workers behind the process manager; Nginx terminates TLS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
