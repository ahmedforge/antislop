FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --require-hashes -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic ./alembic
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
