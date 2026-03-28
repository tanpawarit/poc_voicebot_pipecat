FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --no-dev

COPY common/ common/
COPY app_s2s/ app_s2s/
COPY certs/ certs/

FROM base AS s2s
EXPOSE 7861
CMD ["uv", "run", "python", "-m", "app_s2s"]
