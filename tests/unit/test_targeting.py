"""Unit tests for targeting strategies."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from hypeagent.config.schema import HypeagentConfig, TargetingConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.content import Content
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import PlatformConnector
from hypeagent.targeting.registry import TargetingStrategyError, apply_strategy, get_strategy


def _content(
    content_id: str,
    *,
    comment_count: int = 0,
    hours_ago: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> Content:
    return Content(
        id=content_id,
        kind="post",
        author_id="author",
        author_display="author",
        body=f"body-{content_id}",
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        comment_count=comment_count,
        metadata=metadata or {},
    )


def _run_context() -> RunContext:
    config = HypeagentConfig.model_validate(
        {
            "version": 1,
            "name": "targeting-test",
            "platform": {
                "connector": "reddit",
                "base_url": "https://oauth.reddit.com",
                "user_agent": "hypeagent/1.0",
            },
            "llm": {
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openai/gpt-4o-mini",
            },
            "budgets": {"llm_daily_usd": 2.0, "llm_total_usd": 50.0},
            "run": {"agents": ["alice"], "per_agent": {"replies": 1}},
            "targeting": {"strategy": "recent"},
            "personas": {"alice": {"account": "alice", "brief": "Test persona."}},
        }
    )
    secrets = Secrets(
        llm={"api_key": "test-key"},
        accounts={
            "alice": AccountSecret(user_id="t2_agent", token="token"),
        },
    )
    return RunContext(
        run_id="run1",
        mode=RunMode.DRY_RUN,
        config=config,
        secrets=secrets,
        agent_id="alice",
        persona=config.personas["alice"],
        account=secrets.accounts["alice"],
        connector=object(),
        db=object(),
        logger=logging.getLogger("test"),
        llm_client=object(),
        budget_guard=object(),
    )


class TestRegistry:
    def test_get_known_strategy(self) -> None:
        strategy = get_strategy("recent")
        assert strategy.name == "recent"

    def test_get_unknown_strategy_raises(self) -> None:
        with pytest.raises(TargetingStrategyError, match="Unknown targeting strategy"):
            get_strategy("not_a_strategy")


class TestRandomWithCommentsLast24h:
    def test_filters_by_since_hours_and_min_comment_count(self) -> None:
        ctx = _run_context()
        contents = [
            _content("old-no-comments", comment_count=0, hours_ago=30),
            _content("recent-no-comments", comment_count=0, hours_ago=2),
            _content("recent-with-comments", comment_count=3, hours_ago=2),
            _content("old-with-comments", comment_count=5, hours_ago=30),
        ]
        candidates = apply_strategy(
            "random_with_comments_last_24h",
            contents,
            ctx,
            {"since_hours": 24, "min_comment_count": 1},
        )
        assert [content.id for content in candidates] == ["recent-with-comments"]

    def test_uses_default_params(self) -> None:
        ctx = _run_context()
        contents = [
            _content("too-old", comment_count=2, hours_ago=25),
            _content("eligible", comment_count=1, hours_ago=12),
        ]
        candidates = apply_strategy("random_with_comments_last_24h", contents, ctx)
        assert [content.id for content in candidates] == ["eligible"]

    def test_excludes_zero_comment_posts(self) -> None:
        ctx = _run_context()
        contents = [
            _content("a", comment_count=0, hours_ago=1),
            _content("b", comment_count=1, hours_ago=1),
        ]
        candidates = apply_strategy(
            "random_with_comments_last_24h",
            contents,
            ctx,
            {"since_hours": 24, "min_comment_count": 2},
        )
        assert candidates == []


class TestRecent:
    def test_returns_newest_post_with_comments(self) -> None:
        ctx = _run_context()
        contents = [
            _content("older", comment_count=2, hours_ago=10),
            _content("newest", comment_count=1, hours_ago=1),
            _content("no-comments", comment_count=0, hours_ago=0.5),
        ]
        candidates = apply_strategy("recent", contents, ctx)
        assert [content.id for content in candidates] == ["newest"]

    def test_returns_empty_when_no_posts_have_comments(self) -> None:
        ctx = _run_context()
        contents = [
            _content("a", comment_count=0, hours_ago=1),
            _content("b", comment_count=0, hours_ago=2),
        ]
        assert apply_strategy("recent", contents, ctx) == []


class TestOldestUnanswered:
    def test_returns_oldest_post_with_fewest_agent_comments(self) -> None:
        ctx = _run_context()
        contents = [
            _content("answered-newer", hours_ago=2, metadata={"agent_comment_count": 2}),
            _content("unanswered-newer", hours_ago=3, metadata={"agent_comment_count": 0}),
            _content("unanswered-oldest", hours_ago=10, metadata={"agent_comment_count": 0}),
            _content("answered-oldest", hours_ago=12, metadata={"agent_comment_count": 1}),
        ]
        candidates = apply_strategy("oldest_unanswered", contents, ctx)
        assert [content.id for content in candidates] == ["unanswered-oldest"]

    def test_defaults_missing_metadata_to_zero(self) -> None:
        ctx = _run_context()
        contents = [
            _content("with-meta", hours_ago=1, metadata={"agent_comment_count": 1}),
            _content("without-meta", hours_ago=5),
        ]
        candidates = apply_strategy("oldest_unanswered", contents, ctx)
        assert [content.id for content in candidates] == ["without-meta"]


class TestAllowlist:
    def test_preserves_allowlist_order(self) -> None:
        ctx = _run_context()
        contents = [
            _content("post-b"),
            _content("post-a"),
            _content("post-c"),
        ]
        candidates = apply_strategy(
            "allowlist",
            contents,
            ctx,
            {"content_ids": ["post-c", "post-a"]},
        )
        assert [content.id for content in candidates] == ["post-c", "post-a"]

    def test_ignores_missing_ids(self) -> None:
        ctx = _run_context()
        contents = [_content("post-a")]
        candidates = apply_strategy(
            "allowlist",
            contents,
            ctx,
            {"content_ids": ["post-a", "missing"]},
        )
        assert [content.id for content in candidates] == ["post-a"]

    def test_returns_empty_for_missing_or_empty_allowlist(self) -> None:
        ctx = _run_context()
        contents = [_content("post-a")]
        assert apply_strategy("allowlist", contents, ctx, {}) == []
        assert apply_strategy("allowlist", contents, ctx, {"content_ids": []}) == []


class TestPlatformFilterCandidates:
    def test_connector_delegates_to_registry(self) -> None:
        class StubConnector(PlatformConnector):
            name = "stub"

            def list_contents(self, ctx, *, since):
                return []

            def get_thread(self, ctx, content_id):
                raise NotImplementedError

            def publish_comment(self, ctx, content_id, text, parent_comment_id):
                raise NotImplementedError

        ctx = _run_context()
        connector = StubConnector(
            ctx.config.platform,
            ctx.account,
            ctx.config.http,
        )
        contents = [
            _content("skip", comment_count=0, hours_ago=1),
            _content("keep", comment_count=2, hours_ago=1),
        ]
        targeting = TargetingConfig(
            strategy="random_with_comments_last_24h",
            params={"since_hours": 24, "min_comment_count": 1},
        )
        filtered = connector.filter_candidates(ctx, contents, targeting)
        assert [content.id for content in filtered] == ["keep"]
