FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install deps first (layer caching)
COPY pyproject.toml .python-version ./
RUN uv sync --no-dev

# Copy source (no mt5 extra — MT5 requires Windows)
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
