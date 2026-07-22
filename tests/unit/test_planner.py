"""Unit tests for action planner."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from hypeagent.agent.planner import Planner
from hypeagent.config.schema import HypeagentConfig, PerAgentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.action import ActionType
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import PlatformConnector


class _StubConnector(PlatformConnector):
    name = "stub"

    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        raise NotImplementedError

    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        raise NotImplementedError

    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        raise NotImplementedError


def _run_context(*, reply_depth_max: int = 2) -> RunContext:
    config = HypeagentConfig.model_validate(
        {
            "version": 1,
            "name": "planner-test",
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
            "run": {
                "agents": ["alice"],
                "per_agent": {"replies": 1},
                "reply_depth_max": reply_depth_max,
            },
            "targeting": {"strategy": "recent"},
            "personas": {"alice": {"account": "alice", "brief": "Test persona."}},
        }
    )
    secrets = Secrets(
        llm={"api_key": "test-key"},
        accounts={"alice": AccountSecret(user_id="t2_agent", token="token")},
    )
    return RunContext(
        run_id="run1",
        mode=RunMode.DRY_RUN,
        config=config,
        secrets=secrets,
        agent_id="alice",
        persona=config.personas["alice"],
        account=secrets.accounts["alice"],
        connector=_StubConnector(config.platform, secrets.accounts["alice"], config.http),
        db=object(),
        logger=logging.getLogger("test"),
        llm_client=object(),
        budget_guard=object(),
    )


def _thread(*, comments: list[Comment] | None = None) -> Thread:
    content = Content(
        id="post1",
        kind="post",
        author_id="author",
        author_display="author",
        body="Post body",
        created_at=datetime.now(UTC),
        comment_count=len(comments or []),
        metadata={},
    )
    return Thread(content=content, comments=comments or [])


def _comment(comment_id: str, *, depth: int = 0) -> Comment:
    return Comment(
        id=comment_id,
        content_id="post1",
        parent_id=None,
        author_id="user",
        author_display="user",
        body=f"comment {comment_id}",
        created_at=datetime.now(UTC),
        depth=depth,
        metadata={},
    )


class TestPlanner:
    def test_prefers_reply_when_quota_and_comments_exist(self) -> None:
        ctx = _run_context()
        thread = _thread(comments=[_comment("c1"), _comment("c2")])
        decision = Planner().decide(PerAgentConfig(replies=1), thread, ctx)
        assert decision is not None
        assert decision.action_type == ActionType.REPLY
        assert decision.parent is not None
        assert decision.parent.id in {"c1", "c2"}

    def test_comment_when_only_comment_quota(self) -> None:
        ctx = _run_context()
        thread = _thread(comments=[_comment("c1")])
        decision = Planner().decide(PerAgentConfig(comments=1, replies=0), thread, ctx)
        assert decision is not None
        assert decision.action_type == ActionType.COMMENT
        assert decision.parent is None

    def test_skips_when_no_quota(self) -> None:
        ctx = _run_context()
        thread = _thread(comments=[_comment("c1")])
        decision = Planner().decide(PerAgentConfig(comments=0, replies=0), thread, ctx)
        assert decision is None

    def test_reply_fallback_to_comment_when_no_eligible_parent(self) -> None:
        ctx = _run_context(reply_depth_max=0)
        thread = _thread(comments=[_comment("c1", depth=1)])
        decision = Planner().decide(
            PerAgentConfig(comments=1, replies=1),
            thread,
            ctx,
        )
        assert decision is not None
        assert decision.action_type == ActionType.COMMENT
        assert decision.parent is None

    def test_reply_skips_when_no_eligible_and_no_comment_quota(self) -> None:
        ctx = _run_context(reply_depth_max=0)
        thread = _thread(comments=[_comment("c1", depth=1)])
        decision = Planner().decide(PerAgentConfig(replies=1), thread, ctx)
        assert decision is None
