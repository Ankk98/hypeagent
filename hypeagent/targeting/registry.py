"""Targeting strategy loading and application."""

from __future__ import annotations

from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext
from hypeagent.targeting.base import TargetingStrategy
from hypeagent.targeting.strategies.allowlist import AllowlistStrategy
from hypeagent.targeting.strategies.oldest_unanswered import OldestUnansweredStrategy
from hypeagent.targeting.strategies.random_with_comments import RandomWithCommentsLast24hStrategy
from hypeagent.targeting.strategies.recent import RecentStrategy

BUILTIN_STRATEGIES: dict[str, type[TargetingStrategy]] = {
    "random_with_comments_last_24h": RandomWithCommentsLast24hStrategy,
    "recent": RecentStrategy,
    "oldest_unanswered": OldestUnansweredStrategy,
    "allowlist": AllowlistStrategy,
}

_STRATEGY_INSTANCES: dict[str, TargetingStrategy] = {
    name: cls() for name, cls in BUILTIN_STRATEGIES.items()
}


class TargetingStrategyError(Exception):
    """Raised when a targeting strategy cannot be resolved or applied."""


def get_strategy(name: str) -> TargetingStrategy:
    """Return a built-in strategy instance by name."""
    strategy = _STRATEGY_INSTANCES.get(name)
    if strategy is None:
        known = ", ".join(sorted(BUILTIN_STRATEGIES))
        msg = f"Unknown targeting strategy {name!r}; expected one of: {known}"
        raise TargetingStrategyError(msg)
    return strategy


def apply_strategy(
    strategy_name: str,
    contents: list[Content],
    ctx: RunContext,
    params: dict[str, Any] | None = None,
) -> list[Content]:
    """Apply a built-in targeting strategy to candidate content."""
    strategy = get_strategy(strategy_name)
    return strategy.apply(contents, ctx, params or {})
