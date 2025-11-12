FROM python:3.13-slim

WORKDIR /app

RUN adduser --disabled-password --gecos '' app && chown -R app:app /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY --chown=app:app pyproject.toml uv.lock* ./

USER app

RUN uv sync --frozen --no-dev

COPY --chown=app:app . .

CMD ["uv", "run", "--no-dev", "python", "main.py"]
