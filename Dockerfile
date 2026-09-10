FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not invalidate this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

# Never run the API as root inside the container.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000
# PaaS hosts (Koyeb included) inject PORT; local compose uses 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
