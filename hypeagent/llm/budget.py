"""LLM budget enforcement."""

from __future__ import annotations

from hypeagent.config.schema import BudgetConfig
from hypeagent.db.repositories.usage import UsageRepository


class BudgetExceededError(Exception):
    """Raised when daily or total LLM spend cap is reached."""


class BudgetGuard:
    """Check daily/total LLM caps before each completion call."""

    def __init__(self, budgets: BudgetConfig, usage: UsageRepository) -> None:
        self._budgets = budgets
        self._usage = usage

    @property
    def daily_cap(self) -> float:
        return self._budgets.llm_daily_usd

    @property
    def total_cap(self) -> float:
        return self._budgets.llm_total_usd

    def check(self) -> None:
        """Raise BudgetExceededError if either cap is already reached."""
        daily_cost = self._usage.get_daily_cost()
        if daily_cost >= self._budgets.llm_daily_usd:
            msg = (
                f"Daily LLM budget exceeded: ${daily_cost:.2f} >= "
                f"${self._budgets.llm_daily_usd:.2f}"
            )
            raise BudgetExceededError(msg)

        total_cost = self._usage.get_total_cost()
        if total_cost >= self._budgets.llm_total_usd:
            msg = (
                f"Total LLM budget exceeded: ${total_cost:.2f} >= "
                f"${self._budgets.llm_total_usd:.2f}"
            )
            raise BudgetExceededError(msg)
