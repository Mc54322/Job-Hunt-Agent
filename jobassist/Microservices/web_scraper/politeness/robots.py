"""robots.txt checks for company careers sites (one fetch per site, kept in memory)."""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_AGENT_TOKEN = "JobAssist"


class RobotsChecker:
    """Answers "may JobAssist fetch this URL?" per the site's robots.txt.

    A missing robots.txt (4xx) allows everything; an unreachable one (5xx / network
    error) disallows, as RFC 9309 recommends.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        """Return True when robots.txt permits fetching *url*."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = await self._load(origin)
        parser = self._parsers[origin]
        if parser is None:
            return False
        return parser.can_fetch(_AGENT_TOKEN, url)

    async def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            resp = await self._client.get(
                f"{origin}/robots.txt",
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code >= 500:
            return None
        if resp.status_code >= 400:
            parser.parse([])  # no rules: everything allowed
            return parser
        parser.parse(resp.text.splitlines())
        return parser
