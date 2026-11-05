# frontend service — independently deployable FastAPI app.
# Build from the repo root:  docker build -f jobassist/Microservices/frontend/Dockerfile -t jobassist-frontend .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies against the locked environment first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY jobassist ./jobassist
RUN uv sync --frozen --no-dev

EXPOSE 8000
ENV PORT=8000

CMD ["uv", "run", "uvicorn", "jobassist.Microservices.frontend.api:app", "--host", "0.0.0.0", "--port", "8000"]
