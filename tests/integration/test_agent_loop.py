"""Integration tests for the agent loop dry-run."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hypeagent.agent.approval import (
    ApprovalDecision,
    ApprovalPrompt,
    ApprovalQuitError,
    ApprovalResponse,
)
from hypeagent.agent.loop import AgentRunner
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.db.connection import Database
from hypeagent.db.repositories.runs import RunsRepository
from hypeagent.llm.client import LLMResponse
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext, RunMode
from hypeagent.models.action import ActionTargetKind
from hypeagent.platforms.base import PlatformConnector


def _minimal_config(*, agents: list[str] | None = None) -> HypeagentConfig:
    agent_list = agents or ["alice", "bob"]
    return HypeagentConfig.model_validate(
        {
            "version": 1,
            "name": "agent-loop-test",
            "platform": {
                "connector": "reddit",
                "base_url": "https://oauth.reddit.com",
                "user_agent": "hypeagent/1.0",
            },
            "llm": {
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openai/gpt-4o-mini",
            },
            "budgets": {"llm_daily_usd": 2.0, "llm_total_usd": 50.0, "max_actions_per_run": 50},
            "run": {
                "agents": agent_list,
                "per_agent": {"comments": 0, "replies": 1},
                "reply_depth_max": 2,
            },
            "targeting": {
                "strategy": "random_with_comments_last_24h",
                "params": {"since_hours": 24, "min_comment_count": 1},
            },
            "personas": {
                "alice": {"account": "alice", "brief": "Alice persona."},
                "bob": {"account": "bob", "brief": "Bob persona."},
            },
        }
    )


def _secrets() -> Secrets:
    return Secrets(
        llm={"api_key": "test-key"},
        accounts={
            "alice": AccountSecret(user_id="t2_alice", token="token-a"),
            "bob": AccountSecret(user_id="t2_bob", token="token-b"),
        },
    )


def _content(content_id: str) -> Content:
    return Content(
        id=content_id,
        kind="post",
        author_id="author",
        author_display="author",
        body=f"Body for {content_id}",
        created_at=datetime.now(UTC) - timedelta(hours=2),
        comment_count=2,
        metadata={},
    )


def _comment(comment_id: str, content_id: str) -> Comment:
    return Comment(
        id=comment_id,
        content_id=content_id,
        parent_id=None,
        author_id="other",
        author_display="other_user",
        body=f"Comment {comment_id}",
        created_at=datetime.now(UTC) - timedelta(hours=1),
        depth=0,
        metadata={},
    )


class MockConnector(PlatformConnector):
    """In-memory connector for agent loop tests."""

    name = "mock"

    def __init__(
        self,
        contents: list[Content],
        threads: dict[str, Thread],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._contents = contents
        self._threads = threads
        self.publish_calls: list[tuple[str, str, str | None]] = []

    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        _ = ctx
        return [c for c in self._contents if c.created_at >= since]

    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        _ = ctx
        return self._threads[content_id]

    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        _ = ctx
        self.publish_calls.append((content_id, text, parent_comment_id))
        return _comment("published-1", content_id)


@pytest.fixture
def mock_llm() -> MagicMock:
    client = MagicMock()
    client.complete.return_value = LLMResponse(
        content="Haan yaar same feeling",
        model="openai/gpt-4o-mini",
        tokens_in=50,
        tokens_out=10,
        cost_usd=0.001,
    )
    return client


class TestAgentLoopDryRun:
    def test_dry_run_proposes_actions_for_all_agents(
        self,
        tmp_path,
        mock_llm: MagicMock,
    ) -> None:
        config = _minimal_config()
        secrets = _secrets()
        db_path = tmp_path / "agent.db"

        def connector_loader(name: str) -> type[PlatformConnector]:
            assert name == "reddit"

            class _Loader(MockConnector):
                def __init__(
                    self,
                    platform_config: Any,
                    account: AccountSecret,
                    http: Any,
                ) -> None:
                    super().__init__(
                        [_content("post-a"), _content("post-b")],
                        {
                            "post-a": Thread(
                                content=_content("post-a"),
                                comments=[_comment("c1", "post-a")],
                            ),
                            "post-b": Thread(
                                content=_content("post-b"),
                                comments=[_comment("c2", "post-b")],
                            ),
                        },
                        platform_config=platform_config,
                        account=account,
                        http=http,
                    )

            return _Loader

        with (
            patch("hypeagent.agent.loop.load_connector", side_effect=connector_loader),
            patch("hypeagent.agent.loop.LLMClient", return_value=mock_llm),
            Database(db_path) as db,
        ):
            runner = AgentRunner(
                config,
                secrets,
                db,
                logger=logging.getLogger("test.agent"),
            )
            result = runner.run_all(RunMode.DRY_RUN)

        assert result.status == "completed"
        assert len(result.proposed_actions) == 2
        assert result.proposed_actions[0].draft_text == "Haan yaar same feeling"
        assert result.published_actions == []

        with Database(db_path) as db:
            runs_repo = RunsRepository(db)
            stored = runs_repo.get_proposed_for_run(result.run_id)
            assert len(stored) == 2
            agent_ids = {row.agent_id for row in stored}
            assert agent_ids == {"alice", "bob"}

            run_row = db.conn.execute(
                "SELECT status, actions_proposed, actions_published FROM runs WHERE run_id = ?",
                (result.run_id,),
            ).fetchone()
            assert run_row is not None
            assert run_row["status"] == "completed"
            assert run_row["actions_proposed"] == 2
            assert run_row["actions_published"] == 0

    def test_skips_agent_when_no_candidates(self, tmp_path, mock_llm: MagicMock) -> None:
        config = _minimal_config(agents=["alice"])
        secrets = _secrets()
        db_path = tmp_path / "empty.db"

        class EmptyConnector(MockConnector):
            def __init__(
                self,
                platform_config: Any,
                account: AccountSecret,
                http: Any,
            ) -> None:
                super().__init__(
                    [],
                    {},
                    platform_config=platform_config,
                    account=account,
                    http=http,
                )

            def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
                _ = ctx, since
                return []

        with (
            patch("hypeagent.agent.loop.load_connector", return_value=EmptyConnector),
            patch("hypeagent.agent.loop.LLMClient", return_value=mock_llm),
            Database(db_path) as db,
        ):
            result = AgentRunner(config, secrets, db).run_all(RunMode.DRY_RUN)

        assert result.status == "completed"
        assert result.proposed_actions == []

    def test_respects_max_actions_per_run(self, tmp_path, mock_llm: MagicMock) -> None:
        config = HypeagentConfig.model_validate(
            {
                **_minimal_config().model_dump(),
                "budgets": {"llm_daily_usd": 2.0, "llm_total_usd": 50.0, "max_actions_per_run": 1},
                "run": {
                    "agents": ["alice", "bob", "carol"],
                    "per_agent": {"comments": 0, "replies": 1},
                    "reply_depth_max": 2,
                },
                "personas": {
                    "alice": {"account": "alice", "brief": "Alice persona."},
                    "bob": {"account": "bob", "brief": "Bob persona."},
                    "carol": {"account": "alice", "brief": "Carol persona."},
                },
            }
        )
        secrets = _secrets()
        db_path = tmp_path / "capped.db"

        def connector_loader(name: str) -> type[PlatformConnector]:
            _ = name

            class _Loader(MockConnector):
                def __init__(
                    self,
                    platform_config: Any,
                    account: AccountSecret,
                    http: Any,
                ) -> None:
                    super().__init__(
                        [_content("post-a")],
                        {
                            "post-a": Thread(
                                content=_content("post-a"),
                                comments=[_comment("c1", "post-a")],
                            ),
                        },
                        platform_config=platform_config,
                        account=account,
                        http=http,
                    )

            return _Loader

        with (
            patch("hypeagent.agent.loop.load_connector", side_effect=connector_loader),
            patch("hypeagent.agent.loop.LLMClient", return_value=mock_llm),
            Database(db_path) as db,
        ):
            result = AgentRunner(config, secrets, db).run_all(RunMode.DRY_RUN)

        assert len(result.proposed_actions) == 1

    def test_dry_run_comment_then_reaction_same_agent(
        self,
        tmp_path,
        mock_llm: MagicMock,
    ) -> None:
        """per_agent quotas of comments+reactions yield two proposals on one post."""
        from hypeagent.models.action import ActionKind, ActionTarget, PublishResult
        from hypeagent.platforms.base import PlatformCapabilities, ReactionCapability

        config = HypeagentConfig.model_validate(
            {
                **_minimal_config(agents=["alice"]).model_dump(),
                "run": {
                    "agents": ["alice"],
                    "per_agent": {"comments": 1, "replies": 0, "reactions": 1},
                    "action_priority": ["comment", "reaction", "reply"],
                    "reply_depth_max": 2,
                },
                "engagement": {
                    "reactions": {
                        "enabled": True,
                        "targets": ["content"],
                        "types": ["agree", "like"],
                        "strategy": "weighted",
                        "weights": {"agree": 0.5, "like": 0.5},
                        "skip_if_already_reacted": True,
                    }
                },
            }
        )
        secrets = _secrets()
        db_path = tmp_path / "multi.db"

        class ReactingConnector(MockConnector):
            def capabilities(self) -> PlatformCapabilities:
                return PlatformCapabilities(
                    reactions=ReactionCapability(
                        target_kinds=frozenset({ActionTargetKind.CONTENT}),
                        allowed_types=frozenset({"agree", "like"}),
                        mode="toggle",
                    )
                )

            def publish_reaction(
                self,
                ctx: RunContext,
                target: ActionTarget,
                reaction_type: str,
            ) -> PublishResult:
                _ = ctx
                return PublishResult(
                    platform_object_id=f"rxn-{target.id}-{reaction_type}",
                    raw={"type": reaction_type},
                )

            def current_engagement(
                self,
                ctx: RunContext,
                target: ActionTarget,
            ) -> dict[str, Any]:
                _ = ctx, target
                return {"myReaction": None}

        def connector_loader(name: str) -> type[PlatformConnector]:
            _ = name

            class _Loader(ReactingConnector):
                def __init__(
                    self,
                    platform_config: Any,
                    account: AccountSecret,
                    http: Any,
                ) -> None:
                    super().__init__(
                        [_content("post-a")],
                        {
                            "post-a": Thread(
                                content=_content("post-a"),
                                comments=[_comment("c1", "post-a")],
                            ),
                        },
                        platform_config=platform_config,
                        account=account,
                        http=http,
                    )

            return _Loader

        with (
            patch("hypeagent.agent.loop.load_connector", side_effect=connector_loader),
            patch("hypeagent.agent.loop.LLMClient", return_value=mock_llm),
            Database(db_path) as db,
        ):
            result = AgentRunner(config, secrets, db).run_all(RunMode.DRY_RUN)

        assert result.status == "completed"
        assert len(result.proposed_actions) == 2
        kinds = [p.action_type for p in result.proposed_actions]
        assert kinds == [ActionKind.COMMENT, ActionKind.REACT]
        assert result.proposed_actions[0].content_id == result.proposed_actions[1].content_id
        assert result.proposed_actions[1].reaction_type in {"agree", "like"}


class TestAgentLoopPublishModes:
    def _run_with_connector(
        self,
        tmp_path,
        mock_llm: MagicMock,
        *,
        mode: RunMode,
        approval: ApprovalPrompt | None = None,
        agents: list[str] | None = None,
    ):
        config = _minimal_config(agents=agents or ["alice"])
        secrets = _secrets()
        db_path = tmp_path / f"{mode.value}.db"

        connector_instance: MockConnector | None = None

        def connector_loader(name: str) -> type[PlatformConnector]:
            assert name == "reddit"

            class _Loader(MockConnector):
                def __init__(
                    self,
                    platform_config: Any,
                    account: AccountSecret,
                    http: Any,
                ) -> None:
                    nonlocal connector_instance
                    super().__init__(
                        [_content("post-a")],
                        {
                            "post-a": Thread(
                                content=_content("post-a"),
                                comments=[_comment("c1", "post-a")],
                            ),
                        },
                        platform_config=platform_config,
                        account=account,
                        http=http,
                    )
                    connector_instance = self

            return _Loader

        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(
                patch("hypeagent.agent.loop.load_connector", side_effect=connector_loader)
            )
            stack.enter_context(
                patch("hypeagent.agent.loop.LLMClient", return_value=mock_llm)
            )
            if approval is not None:
                stack.enter_context(
                    patch("hypeagent.agent.loop.ApprovalPrompt", return_value=approval)
                )
            db = stack.enter_context(Database(db_path))
            runner = AgentRunner(config, secrets, db)
            result = runner.run_all(mode)

        assert connector_instance is not None
        return result, connector_instance, db_path

    def test_auto_mode_publishes(self, tmp_path, mock_llm: MagicMock) -> None:
        result, connector, db_path = self._run_with_connector(
            tmp_path,
            mock_llm,
            mode=RunMode.AUTO,
        )

        assert result.status == "completed"
        assert len(result.proposed_actions) == 1
        assert len(result.published_actions) == 1
        assert result.published_actions[0].approved_by == "auto"
        assert len(connector.publish_calls) == 1

        with Database(db_path) as db:
            stored = RunsRepository(db).get_proposed_for_run(result.run_id)
            assert stored[0].published is True
            assert stored[0].platform_comment_id == "published-1"

    def test_approve_mode_publishes_on_yes(self, tmp_path, mock_llm: MagicMock) -> None:
        approval = MagicMock(spec=ApprovalPrompt)
        approval.prompt.return_value = ApprovalResponse(
            ApprovalDecision.PUBLISH,
            "Haan yaar same feeling",
        )

        result, connector, _ = self._run_with_connector(
            tmp_path,
            mock_llm,
            mode=RunMode.APPROVE,
            approval=approval,
        )

        assert len(result.published_actions) == 1
        assert result.published_actions[0].approved_by == "human"
        assert len(connector.publish_calls) == 1
        approval.prompt.assert_called_once()

    def test_approve_mode_skips_on_no(self, tmp_path, mock_llm: MagicMock) -> None:
        approval = MagicMock(spec=ApprovalPrompt)
        approval.prompt.return_value = ApprovalResponse(
            ApprovalDecision.SKIP,
            "Haan yaar same feeling",
        )

        result, connector, db_path = self._run_with_connector(
            tmp_path,
            mock_llm,
            mode=RunMode.APPROVE,
            approval=approval,
        )

        assert result.published_actions == []
        assert connector.publish_calls == []

        with Database(db_path) as db:
            stored = RunsRepository(db).get_proposed_for_run(result.run_id)
            assert stored[0].published is False

    def test_approve_mode_quit_raises(self, tmp_path, mock_llm: MagicMock) -> None:
        approval = MagicMock(spec=ApprovalPrompt)
        approval.prompt.return_value = ApprovalResponse(
            ApprovalDecision.QUIT,
            "Haan yaar same feeling",
        )

        with pytest.raises(ApprovalQuitError):
            self._run_with_connector(
                tmp_path,
                mock_llm,
                mode=RunMode.APPROVE,
                approval=approval,
            )

    def test_approve_mode_updates_edited_draft(self, tmp_path, mock_llm: MagicMock) -> None:
        approval = MagicMock(spec=ApprovalPrompt)
        approval.prompt.return_value = ApprovalResponse(
            ApprovalDecision.PUBLISH,
            "Edited by human",
        )

        result, connector, db_path = self._run_with_connector(
            tmp_path,
            mock_llm,
            mode=RunMode.APPROVE,
            approval=approval,
        )

        assert connector.publish_calls[0][1] == "Edited by human"

        with Database(db_path) as db:
            stored = RunsRepository(db).get_proposed_for_run(result.run_id)
            assert stored[0].draft_text == "Edited by human"
            assert result.proposed_actions[0].draft_text == "Edited by human"

