# cv_feedback_provider service — independently deployable FastAPI app.
# Build from the repo root:  docker build -f jobassist/Microservices/cv_feedback_provider/Dockerfile -t jobassist-cv_feedback_provider .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies against the locked environment first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY jobassist ./jobassist
RUN uv sync --frozen --no-dev

EXPOSE 8004
ENV PORT=8004

CMD ["uv", "run", "uvicorn", "jobassist.Microservices.cv_feedback_provider.api:app", "--host", "0.0.0.0", "--port", "8004"]
