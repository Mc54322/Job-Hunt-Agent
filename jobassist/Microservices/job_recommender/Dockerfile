# job_recommender service — independently deployable FastAPI app.
# Build from the repo root:  docker build -f jobassist/Microservices/job_recommender/Dockerfile -t jobassist-job_recommender .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies against the locked environment first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY jobassist ./jobassist
RUN uv sync --frozen --no-dev

EXPOSE 8003
ENV PORT=8003

CMD ["uv", "run", "uvicorn", "jobassist.Microservices.job_recommender.api:app", "--host", "0.0.0.0", "--port", "8003"]
