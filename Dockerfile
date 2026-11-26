FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY sdk ./sdk
COPY app ./app
COPY docs/aevum_testnet_deployment.json ./docs/aevum_testnet_deployment.json

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV HOST=0.0.0.0 \
    PORT=8784 \
    AEVUM_UI_MODE=live \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8784

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8784/health', timeout=4).read()"]

CMD ["python", "-m", "app.payee_ui"]
