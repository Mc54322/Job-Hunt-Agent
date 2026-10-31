"""Spending meter for Claude calls — run and per-employer limits, with a cost breakdown.

Every Claude call in a search goes through `metered_create`, which checks the limits
(and the user's Stop button) before the call and records the real cost from the
response's `usage` afterwards. Costs are estimates from published prices; the
Anthropic console is the official record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic
from pydantic import BaseModel

# claude-sonnet-4-6, USD per million tokens; web search per request.
_INPUT_PER_MTOK = 3.00
_OUTPUT_PER_MTOK = 15.00
_CACHE_WRITE_PER_MTOK = 3.75
_CACHE_READ_PER_MTOK = 0.30
_WEB_SEARCH_EACH = 0.01


class BudgetStop(Exception):
    """No more Claude calls this run (limit reached, stopped by the user, no credit)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EmployerLimit(Exception):
    """This employer has reached its own spending limit; skip its remaining Claude work."""


class CallFailed(Exception):
    """One Claude call failed for a reason specific to it; the run carries on."""


class CostLine(BaseModel):
    """Spend for one employer and step."""

    company: str
    step: str
    usd: float
    calls: int
    web_searches: int


@dataclass
class _Tally:
    usd: float = 0.0
    calls: int = 0
    web_searches: int = 0


def _count(obj: Any, name: str) -> int:
    value = getattr(obj, name, 0)
    return value if isinstance(value, int) else 0


def usage_cost(usage: Any) -> tuple[float, int]:
    """Return ``(usd, web_searches)`` for a response's ``usage``."""
    tokens = (
        _count(usage, "input_tokens") * _INPUT_PER_MTOK
        + _count(usage, "output_tokens") * _OUTPUT_PER_MTOK
        + _count(usage, "cache_creation_input_tokens") * _CACHE_WRITE_PER_MTOK
        + _count(usage, "cache_read_input_tokens") * _CACHE_READ_PER_MTOK
    ) / 1_000_000
    searches = _count(getattr(usage, "server_tool_use", None), "web_search_requests")
    return tokens + searches * _WEB_SEARCH_EACH, searches


def estimate_input_cost(chars: int, max_output_tokens: int = 0) -> float:
    """Rough upper-bound cost of sending *chars* of text (~4 chars per token)."""
    return (chars / 4 * _INPUT_PER_MTOK + max_output_tokens * _OUTPUT_PER_MTOK) / 1_000_000


class CostMeter:
    """Tracks spend for one run and enforces its limits."""

    def __init__(
        self,
        budget_usd: float | None = None,
        company_budget_usd: float | None = None,
    ) -> None:
        self.budget_usd = budget_usd
        self.company_budget_usd = company_budget_usd
        self.spent_usd = 0.0
        self.stopped: str | None = None  # why Claude calls stopped, once they have
        self._tallies: dict[tuple[str, str], _Tally] = {}

    def cancel(self, reason: str = "Stopped by you.") -> None:
        if self.stopped is None:
            self.stopped = reason

    def company_spent(self, company: str) -> float:
        return sum(t.usd for (c, _), t in self._tallies.items() if c == company)

    def check(self, company: str, step: str, estimate: float = 0.0) -> None:
        """Raise when a call costing about *estimate* would break a limit."""
        if self.stopped:
            raise BudgetStop(self.stopped)
        if self.budget_usd is not None and self.spent_usd + estimate >= self.budget_usd:
            self.stopped = (
                f"Spending limit of ${self.budget_usd:.2f} reached "
                f"(spent ${self.spent_usd:.2f}). Everything found so far is kept."
            )
            raise BudgetStop(self.stopped)
        if (
            company
            and self.company_budget_usd is not None
            and self.company_spent(company) + estimate > self.company_budget_usd
        ):
            raise EmployerLimit(
                f"skipped {step} — it would take this employer past its "
                f"${self.company_budget_usd:.2f} limit (estimated ${estimate:.2f}, "
                f"already ${self.company_spent(company):.2f})"
            )

    def record(self, company: str, step: str, usage: Any) -> float:
        usd, searches = usage_cost(usage)
        tally = self._tallies.setdefault((company, step), _Tally())
        tally.usd += usd
        tally.calls += 1
        tally.web_searches += searches
        self.spent_usd += usd
        return usd

    def raise_for(self, exc: anthropic.APIError) -> None:
        """Turn an API error into BudgetStop (account-wide problem) or CallFailed."""
        message = str(getattr(exc, "message", exc))
        if "credit balance" in message.lower():
            self.stopped = (
                "Your Anthropic credit ran out. Top up at console.anthropic.com, then run "
                "the search again — finished work is saved and won't be paid for twice."
            )
            raise BudgetStop(self.stopped) from exc
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            self.stopped = "Your Anthropic API key was rejected. Check the .env file."
            raise BudgetStop(self.stopped) from exc
        raise CallFailed(message) from exc

    def lines(self) -> list[CostLine]:
        return [
            CostLine(company=c, step=s, usd=round(t.usd, 4), calls=t.calls,
                     web_searches=t.web_searches)
            for (c, s), t in sorted(self._tallies.items(), key=lambda kv: -kv[1].usd)
        ]


async def metered_create(
    client: anthropic.AsyncAnthropic,
    meter: CostMeter | None,
    company: str,
    step: str,
    *,
    estimate: float = 0.0,
    **kwargs: Any,
) -> anthropic.types.Message:
    """``client.messages.create(**kwargs)`` with limit checks and cost recording."""
    if meter is not None:
        meter.check(company, step, estimate)
    try:
        response: anthropic.types.Message = await client.messages.create(**kwargs)
    except anthropic.APIError as exc:
        if meter is None:
            raise
        meter.raise_for(exc)
        raise  # unreachable: raise_for always raises
    if meter is not None:
        meter.record(company, step, response.usage)
    return response
