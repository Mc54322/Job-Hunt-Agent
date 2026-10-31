# list_builder service — independently deployable FastAPI app.
# Build from the repo root:  docker build -f jobassist/Microservices/list_builder/Dockerfile -t jobassist-list_builder .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies against the locked environment first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY jobassist ./jobassist
RUN uv sync --frozen --no-dev

EXPOSE 8005
ENV PORT=8005

CMD ["uv", "run", "uvicorn", "jobassist.Microservices.list_builder.api:app", "--host", "0.0.0.0", "--port", "8005"]
