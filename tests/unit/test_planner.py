"""Unit tests for action planner."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from hypeagent.agent.planner import Planner
from hypeagent.config.schema import HypeagentConfig, PerAgentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.action import ActionKind, ActionTarget, ActionTargetKind
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import (
    PlatformCapabilities,
    PlatformConnector,
    ReactionCapability,
    VoteCapability,
)


class _StubConnector(PlatformConnector):
    name = "stub"

    def __init__(
        self,
        *args: Any,
        reaction_caps: ReactionCapability | None = None,
        vote_caps: VoteCapability | None = None,
        engagement: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._reaction_caps = reaction_caps
        self._vote_caps = vote_caps
        self._engagement = engagement or {}

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

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            reactions=self._reaction_caps,
            votes=self._vote_caps,
        )

    def current_engagement(
        self, ctx: RunContext, target: ActionTarget
    ) -> dict[str, Any]:
        _ = ctx
        return dict(self._engagement.get(target.id, {}))


def _run_context(
    *,
    reply_depth_max: int = 2,
    reaction_caps: ReactionCapability | None = None,
    vote_caps: VoteCapability | None = None,
    engagement_cfg: dict[str, object] | None = None,
    engagement_state: dict[str, Any] | None = None,
    action_priority: list[str] | None = None,
) -> RunContext:
    run: dict[str, object] = {
        "agents": ["alice"],
        "per_agent": {"replies": 1},
        "reply_depth_max": reply_depth_max,
    }
    if action_priority is not None:
        run["action_priority"] = action_priority
    data: dict[str, object] = {
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
        "run": run,
        "targeting": {"strategy": "recent"},
        "personas": {"alice": {"account": "alice", "brief": "Test persona."}},
    }
    if engagement_cfg is not None:
        data["engagement"] = engagement_cfg
    config = HypeagentConfig.model_validate(data)
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
        connector=_StubConnector(
            config.platform,
            secrets.accounts["alice"],
            config.http,
            reaction_caps=reaction_caps,
            vote_caps=vote_caps,
            engagement=engagement_state,
        ),
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


def _reaction_caps(
    *,
    targets: frozenset[ActionTargetKind] | None = None,
) -> ReactionCapability:
    return ReactionCapability(
        target_kinds=targets
        or frozenset({ActionTargetKind.CONTENT, ActionTargetKind.COMMENT}),
        allowed_types=frozenset({"agree", "like", "insightful"}),
        mode="toggle",
    )


class TestPlanner:
    def test_prefers_reply_when_quota_and_comments_exist(self) -> None:
        ctx = _run_context()
        thread = _thread(comments=[_comment("c1"), _comment("c2")])
        decision = Planner().decide(PerAgentConfig(replies=1), thread, ctx)
        assert decision is not None
        assert decision.spec.kind == ActionKind.REPLY
        assert decision.spec.target.kind == ActionTargetKind.COMMENT
        assert decision.spec.target.id in {"c1", "c2"}
        assert decision.spec.payload.text is None

    def test_comment_when_only_comment_quota(self) -> None:
        ctx = _run_context()
        thread = _thread(comments=[_comment("c1")])
        decision = Planner().decide(PerAgentConfig(comments=1, replies=0), thread, ctx)
        assert decision is not None
        assert decision.spec.kind == ActionKind.COMMENT
        assert decision.spec.target.kind == ActionTargetKind.CONTENT
        assert decision.spec.target.id == "post1"

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
        assert decision.spec.kind == ActionKind.COMMENT
        assert decision.spec.target.kind == ActionTargetKind.CONTENT

    def test_reply_skips_when_no_eligible_and_no_comment_quota(self) -> None:
        ctx = _run_context(reply_depth_max=0)
        thread = _thread(comments=[_comment("c1", depth=1)])
        decision = Planner().decide(PerAgentConfig(replies=1), thread, ctx)
        assert decision is None

    def test_react_when_reaction_quota_and_caps(self) -> None:
        ctx = _run_context(
            reaction_caps=_reaction_caps(targets=frozenset({ActionTargetKind.CONTENT})),
            engagement_cfg={
                "reactions": {
                    "enabled": True,
                    "targets": ["content"],
                    "types": ["agree", "like"],
                    "strategy": "random",
                }
            },
            action_priority=["reaction", "comment", "reply"],
        )
        thread = _thread()
        decision = Planner().decide(
            PerAgentConfig(comments=0, replies=0, reactions=1),
            thread,
            ctx,
        )
        assert decision is not None
        assert decision.spec.kind == ActionKind.REACT
        assert decision.spec.target.kind == ActionTargetKind.CONTENT
        assert decision.spec.payload.reaction_type in {"agree", "like"}

    def test_react_skips_when_already_reacted(self) -> None:
        ctx = _run_context(
            reaction_caps=_reaction_caps(targets=frozenset({ActionTargetKind.CONTENT})),
            engagement_cfg={
                "reactions": {
                    "enabled": True,
                    "targets": ["content"],
                    "types": ["agree"],
                    "strategy": "random",
                    "skip_if_already_reacted": True,
                }
            },
            engagement_state={"post1": {"myReaction": "agree"}},
            action_priority=["reaction"],
        )
        decision = Planner().decide(
            PerAgentConfig(reactions=1, comments=0, replies=0),
            _thread(),
            ctx,
        )
        assert decision is None

    def test_react_without_caps_falls_through(self) -> None:
        ctx = _run_context(action_priority=["reaction", "comment"])
        decision = Planner().decide(
            PerAgentConfig(reactions=1, comments=1, replies=0),
            _thread(),
            ctx,
        )
        assert decision is not None
        assert decision.spec.kind == ActionKind.COMMENT

    def test_vote_when_vote_quota_and_caps(self) -> None:
        ctx = _run_context(
            vote_caps=VoteCapability(
                target_kinds=frozenset({ActionTargetKind.CONTENT}),
                allowed_values=frozenset({1, -1, 0}),
                mode="set",
            ),
            engagement_cfg={
                "votes": {
                    "enabled": True,
                    "targets": ["content"],
                    "values": [1],
                }
            },
            action_priority=["vote", "comment", "reply"],
        )
        decision = Planner().decide(
            PerAgentConfig(comments=0, replies=0, votes=1),
            _thread(),
            ctx,
        )
        assert decision is not None
        assert decision.spec.kind == ActionKind.VOTE
        assert decision.spec.target.kind == ActionTargetKind.CONTENT
        assert decision.spec.payload.vote_value == 1

    def test_vote_skips_when_already_voted(self) -> None:
        ctx = _run_context(
            vote_caps=VoteCapability(
                target_kinds=frozenset({ActionTargetKind.CONTENT}),
                allowed_values=frozenset({1}),
                mode="set",
            ),
            engagement_cfg={
                "votes": {
                    "enabled": True,
                    "targets": ["content"],
                    "values": [1],
                    "skip_if_already_voted": True,
                }
            },
            engagement_state={"post1": {"myVote": 1}},
            action_priority=["vote"],
        )
        decision = Planner().decide(
            PerAgentConfig(votes=1, comments=0, replies=0),
            _thread(),
            ctx,
        )
        assert decision is None
