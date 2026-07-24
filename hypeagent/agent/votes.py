"""Vote value selection for VOTE actions."""

from __future__ import annotations

import random

from hypeagent.config.schema import VotesEngagementConfig


def resolve_allowed_values(
    vote_cfg: VotesEngagementConfig,
    connector_allowed: frozenset[int],
) -> list[int]:
    """Intersect config values with connector allowlist (sorted for stability)."""
    if vote_cfg.values is None:
        return sorted(connector_allowed)
    return sorted(set(vote_cfg.values) & set(connector_allowed))


def choose_vote_value(allowed_values: list[int]) -> int | None:
    """Pick one vote value uniformly from the allowlist."""
    if not allowed_values:
        return None
    return random.choice(allowed_values)
