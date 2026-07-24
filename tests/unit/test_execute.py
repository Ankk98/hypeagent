"""Unit tests for connector execute() and ActionSpec helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.action import (
    ActionKind,
    ActionPayload,
    ActionSpec,
    ActionTarget,
    ActionTargetKind,
    ActionType,
    ProposedAction,
    PublishResult,
)
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import (
    PlatformCapabilities,
    PlatformConnector,
    PlatformError,
    ReactionCapability,
    VoteCapability,
)


class _StubConnector(PlatformConnector):
    name = "stub"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.publish_calls: list[tuple[str, str, str | None]] = []

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
        _ = ctx
        self.publish_calls.append((content_id, text, parent_comment_id))
        return Comment(
            id="new-comment",
            content_id=content_id,
            parent_id=parent_comment_id,
            author_id="me",
            author_display="me",
            body=text,
            created_at=datetime.now(UTC),
            depth=0 if parent_comment_id is None else 1,
            metadata={},
        )


def _ctx(connector: PlatformConnector) -> RunContext:
    config = HypeagentConfig.model_validate(
        {
            "version": 1,
            "name": "execute-test",
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
            "run": {"agents": ["alice"], "per_agent": {"comments": 1}},
            "targeting": {"strategy": "recent"},
            "personas": {"alice": {"account": "alice", "brief": "Test."}},
        }
    )
    secrets = Secrets(
        llm={"api_key": "key"},
        accounts={"alice": AccountSecret(user_id="u1", token="tok")},
    )
    return RunContext(
        run_id="run1",
        mode=RunMode.AUTO,
        config=config,
        secrets=secrets,
        agent_id="alice",
        persona=config.personas["alice"],
        account=secrets.accounts["alice"],
        connector=connector,
        db=object(),
        logger=logging.getLogger("test"),
        llm_client=object(),
        budget_guard=object(),
    )


class TestActionTypeAlias:
    def test_action_type_aliases_action_kind(self) -> None:
        assert ActionType is ActionKind
        assert ActionType.COMMENT == ActionKind.COMMENT
        assert ActionType.REPLY == "reply"


class TestProposedActionToSpec:
    def test_comment_spec(self) -> None:
        proposed = ProposedAction(
            run_id="r1",
            agent_id="alice",
            account_id="alice",
            action_type=ActionKind.COMMENT,
            content_id="post1",
            content_body_preview="hello",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="draft body",
            targeting_strategy="recent",
            llm_model="m",
            llm_tokens_in=1,
            llm_tokens_out=1,
            llm_cost_usd=0.0,
        )
        spec = proposed.to_action_spec()
        assert spec.kind == ActionKind.COMMENT
        assert spec.target.kind == ActionTargetKind.CONTENT
        assert spec.target.id == "post1"
        assert spec.payload.text == "draft body"

    def test_reply_spec(self) -> None:
        proposed = ProposedAction(
            run_id="r1",
            agent_id="alice",
            account_id="alice",
            action_type=ActionKind.REPLY,
            content_id="post1",
            content_body_preview="hello",
            parent_comment_id="c1",
            parent_comment_preview="parent",
            draft_text="reply body",
            targeting_strategy="recent",
            llm_model="m",
            llm_tokens_in=1,
            llm_tokens_out=1,
            llm_cost_usd=0.0,
        )
        spec = proposed.to_action_spec()
        assert spec.kind == ActionKind.REPLY
        assert spec.target.kind == ActionTargetKind.COMMENT
        assert spec.target.id == "c1"
        assert spec.payload.text == "reply body"

    def test_react_spec(self) -> None:
        proposed = ProposedAction(
            run_id="r1",
            agent_id="alice",
            account_id="alice",
            action_type=ActionKind.REACT,
            content_id="post1",
            content_body_preview="hello",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="",
            targeting_strategy="recent",
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            reaction_type="agree",
            target_kind=ActionTargetKind.CONTENT,
            target_id="post1",
            payload_json=ActionPayload(reaction_type="agree").to_json(),
        )
        spec = proposed.to_action_spec()
        assert spec.kind == ActionKind.REACT
        assert spec.target.kind == ActionTargetKind.CONTENT
        assert spec.payload.reaction_type == "agree"

    def test_vote_spec(self) -> None:
        proposed = ProposedAction(
            run_id="r1",
            agent_id="alice",
            account_id="alice",
            action_type=ActionKind.VOTE,
            content_id="post1",
            content_body_preview="hello",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="",
            targeting_strategy="recent",
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            vote_value=1,
            target_kind=ActionTargetKind.CONTENT,
            target_id="post1",
            payload_json=ActionPayload(vote_value=1).to_json(),
        )
        spec = proposed.to_action_spec()
        assert spec.kind == ActionKind.VOTE
        assert spec.payload.vote_value == 1
        assert proposed.display_preview() == "1"


class TestConnectorExecute:
    def test_default_capabilities(self) -> None:
        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "caps",
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
                "run": {"agents": ["alice"], "per_agent": {"comments": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _StubConnector(config.platform, account, config.http)
        assert connector.capabilities() == PlatformCapabilities()
        assert connector.capabilities().reactions is None
        assert connector.current_engagement(
            _ctx(connector),
            ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
        ) == {}

    def test_execute_comment_routes_to_publish_comment(self) -> None:
        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"comments": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _StubConnector(config.platform, account, config.http)
        ctx = _ctx(connector)
        spec = ActionSpec(
            kind=ActionKind.COMMENT,
            content_id="post1",
            target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
            payload=ActionPayload(text="hello world"),
        )
        result = connector.execute(ctx, spec)
        assert result.platform_object_id == "new-comment"
        assert connector.publish_calls == [("post1", "hello world", None)]

    def test_execute_reply_passes_parent_id(self) -> None:
        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _StubConnector(config.platform, account, config.http)
        ctx = _ctx(connector)
        spec = ActionSpec(
            kind=ActionKind.REPLY,
            content_id="post1",
            target=ActionTarget(kind=ActionTargetKind.COMMENT, id="c9"),
            payload=ActionPayload(text="reply text"),
        )
        result = connector.execute(ctx, spec)
        assert result.platform_object_id == "new-comment"
        assert connector.publish_calls == [("post1", "reply text", "c9")]

    def test_execute_react_unsupported_raises(self) -> None:
        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"comments": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _StubConnector(config.platform, account, config.http)
        ctx = _ctx(connector)
        spec = ActionSpec(
            kind=ActionKind.REACT,
            content_id="post1",
            target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
            payload=ActionPayload(reaction_type="like"),
        )
        with pytest.raises(PlatformError, match="does not support reactions"):
            connector.execute(ctx, spec)

    def test_execute_react_routes_to_publish_reaction(self) -> None:
        class _ReactingConnector(_StubConnector):
            def capabilities(self) -> PlatformCapabilities:
                return PlatformCapabilities(
                    reactions=ReactionCapability(
                        target_kinds=frozenset({ActionTargetKind.CONTENT}),
                        allowed_types=frozenset({"like"}),
                        mode="set",
                    )
                )

            def publish_reaction(
                self,
                ctx: RunContext,
                target: ActionTarget,
                reaction_type: str,
            ) -> PublishResult:
                _ = ctx
                self.publish_calls.append((target.id, reaction_type, None))
                return PublishResult(platform_object_id=f"rxn-{reaction_type}")

        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"reactions": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _ReactingConnector(config.platform, account, config.http)
        result = connector.execute(
            _ctx(connector),
            ActionSpec(
                kind=ActionKind.REACT,
                content_id="post1",
                target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
                payload=ActionPayload(reaction_type="like"),
            ),
        )
        assert result.platform_object_id == "rxn-like"
        assert connector.publish_calls == [("post1", "like", None)]

    def test_execute_react_requires_publish_reaction_override(self) -> None:
        class _CapsOnlyConnector(_StubConnector):
            def capabilities(self) -> PlatformCapabilities:
                return PlatformCapabilities(
                    reactions=ReactionCapability(
                        target_kinds=frozenset({ActionTargetKind.CONTENT}),
                        allowed_types=frozenset({"like"}),
                        mode="toggle",
                    )
                )

        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"reactions": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _CapsOnlyConnector(config.platform, account, config.http)
        with pytest.raises(PlatformError, match="does not implement publish_reaction"):
            connector.execute(
                _ctx(connector),
                ActionSpec(
                    kind=ActionKind.REACT,
                    content_id="post1",
                    target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
                    payload=ActionPayload(reaction_type="like"),
                ),
            )

    def test_execute_vote_routes_to_publish_vote(self) -> None:
        class _VotingConnector(_StubConnector):
            def capabilities(self) -> PlatformCapabilities:
                return PlatformCapabilities(
                    votes=VoteCapability(
                        target_kinds=frozenset({ActionTargetKind.CONTENT}),
                        allowed_values=frozenset({1, -1, 0}),
                        mode="set",
                    )
                )

            def publish_vote(
                self,
                ctx: RunContext,
                target: ActionTarget,
                vote_value: int,
            ) -> PublishResult:
                _ = ctx
                self.publish_calls.append((target.id, str(vote_value), None))
                return PublishResult(platform_object_id=f"vote-{vote_value}")

        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"votes": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _VotingConnector(config.platform, account, config.http)
        result = connector.execute(
            _ctx(connector),
            ActionSpec(
                kind=ActionKind.VOTE,
                content_id="post1",
                target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
                payload=ActionPayload(vote_value=1),
            ),
        )
        assert result.platform_object_id == "vote-1"
        assert connector.publish_calls == [("post1", "1", None)]

    def test_execute_comment_requires_text(self) -> None:
        config = HypeagentConfig.model_validate(
            {
                "version": 1,
                "name": "exec",
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
                "run": {"agents": ["alice"], "per_agent": {"comments": 1}},
                "targeting": {"strategy": "recent"},
                "personas": {"alice": {"account": "alice", "brief": "Test."}},
            }
        )
        account = AccountSecret(user_id="u1", token="tok")
        connector = _StubConnector(config.platform, account, config.http)
        ctx = _ctx(connector)
        spec = ActionSpec(
            kind=ActionKind.COMMENT,
            content_id="post1",
            target=ActionTarget(kind=ActionTargetKind.CONTENT, id="post1"),
            payload=ActionPayload(),
        )
        with pytest.raises(PlatformError, match="requires payload.text"):
            connector.execute(ctx, spec)
