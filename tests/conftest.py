"""Shared test settings."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from jobassist.Microservices.web_scraper.sources.company_pages.company_site import (
    CompanySiteSearcher,
)


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never launch a real headless browser in tests (slow, and it reaches the network).

    Tests that need a rendered page replace ``_render`` on their own searcher.
    """

    async def _no_render(self: CompanySiteSearcher, url: str) -> str:
        return ""

    monkeypatch.setattr(CompanySiteSearcher, "_render", _no_render)
    yield
