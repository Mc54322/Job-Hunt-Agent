# web_scraper service — independently deployable FastAPI app.
# Build from the repo root:  docker build -f jobassist/Microservices/web_scraper/Dockerfile -t jobassist-web_scraper .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies against the locked environment first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY jobassist ./jobassist
RUN uv sync --frozen --no-dev

EXPOSE 8001
ENV PORT=8001

CMD ["uv", "run", "uvicorn", "jobassist.Microservices.web_scraper.api:app", "--host", "0.0.0.0", "--port", "8001"]
