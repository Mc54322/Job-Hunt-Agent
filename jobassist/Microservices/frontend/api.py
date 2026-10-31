"""FastAPI app for the frontend service — the point-and-click web page.

Serves a single static page and forwards its `/api/*` calls to the job_recommender
(same origin for the browser, so no CORS). No business logic lives here.
Run standalone: `uvicorn jobassist.Microservices.frontend.api:app --port 8000`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

_STATIC = Path(__file__).parent / "static"
_SERVICES = {
    "job_recommender": "JOB_RECOMMENDER_URL",
    "web_scraper": "WEB_SCRAPER_URL",
    "data_cleaner": "DATA_CLEANER_URL",
    "list_builder": "LIST_BUILDER_URL",
}
_DEFAULT_URLS = {
    "job_recommender": "http://localhost:8003",
    "web_scraper": "http://localhost:8001",
    "data_cleaner": "http://localhost:8002",
    "list_builder": "http://localhost:8005",
}
# job_recommender paths the page may call: (method, path prefix).
_ALLOWED = {
    ("POST", "runs"),
    ("GET", "runs/"),
    ("POST", "employers/parse"),
    ("POST", "resume/parse"),
    ("POST", "report"),
    ("POST", "saved"),
    ("POST", "estimate"),
}
# list_builder paths the page may call, under /api/lists/.
_LIST_ALLOWED = {("GET", "template"), ("POST", "preview"), ("POST", "build")}
_SERVICES_DOWN = (
    "JobAssist's background services aren't running. Close JobAssist and start it again."
)


def _url(service: str) -> str:
    return os.environ.get(_SERVICES[service], _DEFAULT_URLS[service]).rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=60.0) as http:
        app.state.http = http
        yield


app = FastAPI(title="JobAssist — Frontend", version="0.1.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "frontend"}


@app.get("/api/health")
async def services_health(request: Request) -> dict[str, Any]:
    """Report which background services are reachable, for the page's status banner."""
    http: httpx.AsyncClient = request.app.state.http
    status: dict[str, bool] = {}
    for service in _SERVICES:
        try:
            resp = await http.get(f"{_url(service)}/health", timeout=3.0)
            status[service] = resp.status_code == 200
        except httpx.HTTPError:
            status[service] = False
    return {"ok": all(status.values()), "services": status}


async def _forward(request: Request, url: str) -> Response:
    http: httpx.AsyncClient = request.app.state.http
    try:
        upstream = await http.request(
            request.method,
            url,
            content=await request.body(),
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    except httpx.HTTPError:
        return JSONResponse({"detail": _SERVICES_DOWN}, status_code=503)
    headers = {}
    if "content-disposition" in upstream.headers:
        headers["Content-Disposition"] = upstream.headers["content-disposition"]
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
        headers=headers,
    )


@app.api_route("/api/lists/{path:path}", methods=["GET", "POST"])
async def lists_proxy(path: str, request: Request) -> Response:
    """Forward allow-listed calls to the list_builder."""
    if (request.method, path) not in _LIST_ALLOWED:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return await _forward(request, f"{_url('list_builder')}/{path}")


@app.api_route("/api/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request) -> Response:
    """Forward allow-listed calls to the job_recommender."""
    if not any(request.method == m and path.startswith(p) for m, p in _ALLOWED):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return await _forward(request, f"{_url('job_recommender')}/{path}")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
