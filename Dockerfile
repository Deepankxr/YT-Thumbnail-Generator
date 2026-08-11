# Thumbnail microservice — Coolify-ready.
# Coolify auto-detects this Dockerfile; it exposes port 8080 and runs uvicorn.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Fonts ship with the repo (SIL OFL) so renders are identical in every
# environment — no reliance on system font packages.
COPY assets ./assets
COPY app ./app

EXPOSE 8080

# Honor Coolify's injected $PORT; default 8080.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
