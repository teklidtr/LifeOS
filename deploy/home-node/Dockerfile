FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src
RUN uv sync --frozen --no-dev --extra mcp

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp/lifeos

RUN mkdir -p /vault /vault/.lifeos /tmp/lifeos \
    && chown -R 10001:10001 /vault /tmp/lifeos

USER 10001:10001
WORKDIR /vault
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()" || exit 1

ENTRYPOINT ["lifeos"]
CMD ["serve", "--config", "/vault/lifeos.yml", "--actor-id", "home-node", "--host", "127.0.0.1"]
