"""Unit tests for vote value helpers."""

from __future__ import annotations

from hypeagent.agent.votes import choose_vote_value, resolve_allowed_values
from hypeagent.config.schema import VotesEngagementConfig


class TestResolveAllowedValues:
    def test_intersects_config_with_connector(self) -> None:
        cfg = VotesEngagementConfig(values=[1, -1])
        assert resolve_allowed_values(cfg, frozenset({1, 0})) == [1]

    def test_all_connector_values_when_unset(self) -> None:
        cfg = VotesEngagementConfig()
        assert resolve_allowed_values(cfg, frozenset({1, -1, 0})) == [-1, 0, 1]


class TestChooseVoteValue:
    def test_picks_from_allowed(self) -> None:
        chosen = choose_vote_value([1, -1])
        assert chosen in {1, -1}

    def test_empty_returns_none(self) -> None:
        assert choose_vote_value([]) is None
