"""Unit tests for engagement config vs connector capabilities."""

from __future__ import annotations

from hypeagent.config.engagement import validate_engagement_against_capabilities
from hypeagent.config.schema import HypeagentConfig
from hypeagent.models.action import ActionTargetKind
from hypeagent.platforms.base import PlatformCapabilities, ReactionCapability, VoteCapability


def _config(**overrides: object) -> HypeagentConfig:
    data: dict[str, object] = {
        "version": 1,
        "name": "engagement-test",
        "platform": {
            "connector": "reddit",
            "base_url": "https://oauth.reddit.com",
            "user_agent": "hypeagent/1.0",
            "subreddit": "test",
        },
        "llm": {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini",
        },
        "budgets": {"llm_daily_usd": 2.0, "llm_total_usd": 50.0},
        "run": {
            "agents": ["alice"],
            "per_agent": {"comments": 0, "replies": 0, "reactions": 1},
        },
        "targeting": {"strategy": "recent"},
        "personas": {"alice": {"account": "alice", "brief": "Test."}},
        "engagement": {
            "reactions": {
                "enabled": True,
                "targets": ["content"],
                "types": ["agree", "like"],
            }
        },
    }
    data.update(overrides)
    return HypeagentConfig.model_validate(data)


def _caps(*, types: set[str] | None = None) -> PlatformCapabilities:
    return PlatformCapabilities(
        reactions=ReactionCapability(
            target_kinds=frozenset({ActionTargetKind.CONTENT}),
            allowed_types=frozenset(types or {"agree", "like", "funny"}),
            mode="toggle",
        )
    )


def _vote_config(**overrides: object) -> HypeagentConfig:
    return _config(
        run={
            "agents": ["alice"],
            "per_agent": {"comments": 0, "replies": 0, "reactions": 0, "votes": 1},
        },
        engagement={
            "votes": {
                "enabled": True,
                "targets": ["content"],
                "values": [1],
            }
        },
        **overrides,
    )


def _vote_caps(*, values: set[int] | None = None) -> PlatformCapabilities:
    return PlatformCapabilities(
        votes=VoteCapability(
            target_kinds=frozenset({ActionTargetKind.CONTENT}),
            allowed_values=frozenset(values or {1, -1, 0}),
            mode="set",
        )
    )


class TestValidateEngagement:
    def test_ok_when_subset(self) -> None:
        assert validate_engagement_against_capabilities(_config(), _caps()) == []

    def test_skips_when_reactions_not_requested(self) -> None:
        config = _config(
            run={"agents": ["alice"], "per_agent": {"comments": 1, "replies": 0}},
            engagement={"reactions": {"enabled": False}},
        )
        assert validate_engagement_against_capabilities(config, PlatformCapabilities()) == []

    def test_rejects_missing_capability(self) -> None:
        errors = validate_engagement_against_capabilities(_config(), PlatformCapabilities())
        assert len(errors) == 1
        assert "does not advertise" in errors[0]

    def test_rejects_unknown_types(self) -> None:
        errors = validate_engagement_against_capabilities(
            _config(),
            _caps(types={"agree"}),
        )
        assert any("like" in e for e in errors)

    def test_rejects_unsupported_targets(self) -> None:
        config = _config(
            engagement={
                "reactions": {
                    "enabled": True,
                    "targets": ["content", "comment"],
                    "types": ["agree"],
                }
            }
        )
        errors = validate_engagement_against_capabilities(config, _caps())
        assert any("comment" in e for e in errors)

    def test_votes_ok_when_subset(self) -> None:
        assert validate_engagement_against_capabilities(_vote_config(), _vote_caps()) == []

    def test_votes_rejects_missing_capability(self) -> None:
        errors = validate_engagement_against_capabilities(
            _vote_config(),
            PlatformCapabilities(),
        )
        assert any("capabilities().votes" in e for e in errors)

    def test_votes_rejects_unknown_values(self) -> None:
        bad = _config(
            run={
                "agents": ["alice"],
                "per_agent": {"comments": 0, "replies": 0, "reactions": 0, "votes": 1},
            },
            engagement={
                "votes": {"enabled": True, "targets": ["content"], "values": [1, -1]}
            },
        )
        errors = validate_engagement_against_capabilities(bad, _vote_caps(values={1}))
        assert any("-1" in e for e in errors)
