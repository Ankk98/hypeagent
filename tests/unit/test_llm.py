"""Unit tests for LLM client, cost estimation, and prompt assembly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hypeagent.config.loader import load_config
from hypeagent.config.schema import BudgetConfig, LLMConfig
from hypeagent.db.connection import Database
from hypeagent.db.repositories.usage import UsageRepository
from hypeagent.llm.budget import BudgetExceededError, BudgetGuard
from hypeagent.llm.client import (
    DEFAULT_COST_PER_TOKEN,
    LLMClient,
    estimate_cost,
)
from hypeagent.llm.prompts import (
    assemble_extra_info_blocks,
    build_drafter_system_prompt,
    build_drafter_user_prompt,
    format_thread_comments,
)
from hypeagent.models.action import ActionType
from hypeagent.models.content import Comment, Content, Thread

EXAMPLE_CONFIG = Path("examples/reddit/hypeagent.yaml")


def _chat_completion_response(
    *,
    content: str = "Haan yaar same feeling",
    prompt_tokens: int = 842,
    completion_tokens: int = 47,
) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_721_600_000,
        "model": "openai/gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _mock_transport(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def database(db_path: Path) -> Database:
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def usage_repo(database: Database) -> UsageRepository:
    return UsageRepository(database)


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o-mini",
        temperature=0.9,
        max_tokens=256,
    )


@pytest.fixture
def budgets() -> BudgetConfig:
    return BudgetConfig(llm_daily_usd=2.0, llm_total_usd=50.0)


def _make_client(
    llm_config: LLMConfig,
    usage_repo: UsageRepository,
    budgets: BudgetConfig,
    *,
    handler: httpx.MockTransport,
    api_key: str = "sk-test",
) -> LLMClient:
    guard = BudgetGuard(budgets, usage_repo)
    http_client = _mock_transport(handler)
    return LLMClient(
        llm_config,
        api_key,
        guard,
        usage_repo,
        http_client=http_client,
    )


class TestEstimateCost:
    def test_known_model_uses_table_rates(self) -> None:
        cost = estimate_cost("openai/gpt-4o-mini", tokens_in=1000, tokens_out=500)
        expected = 1000 * 0.00000015 + 500 * 0.0000006
        assert cost == pytest.approx(expected)

    def test_unknown_model_uses_blended_fallback(self) -> None:
        cost = estimate_cost("vendor/unknown-model", tokens_in=100, tokens_out=50)
        assert cost == pytest.approx(150 * DEFAULT_COST_PER_TOKEN)


class TestLLMClient:
    def test_complete_records_usage(
        self,
        llm_config: LLMConfig,
        usage_repo: UsageRepository,
        budgets: BudgetConfig,
    ) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("Authorization")
            body = json.loads(request.content.decode())
            captured["body"] = body
            return httpx.Response(
                200,
                json=_chat_completion_response(),
            )

        client = _make_client(
            llm_config,
            usage_repo,
            budgets,
            handler=httpx.MockTransport(handler),
        )
        response = client.complete(
            system="You are a persona.",
            messages=[{"role": "user", "content": "Write a reply."}],
            run_id="run-abc",
            agent_id="priya_blr",
        )

        assert response.content == "Haan yaar same feeling"
        assert response.tokens_in == 842
        assert response.tokens_out == 47
        assert response.cost_usd == pytest.approx(
            estimate_cost("openai/gpt-4o-mini", 842, 47)
        )
        assert usage_repo.get_total_cost() == pytest.approx(response.cost_usd)
        assert str(captured["path"]).endswith("/chat/completions")
        assert captured["auth"] == "Bearer sk-test"
        body = captured["body"]
        assert isinstance(body, dict)
        assert body["model"] == "openai/gpt-4o-mini"
        assert body["temperature"] == pytest.approx(0.9)
        assert body["max_tokens"] == 256

        row = usage_repo._db.conn.execute(
            "SELECT run_id, agent_id, model, tokens_in, tokens_out, cost_usd FROM llm_usage"
        ).fetchone()
        assert row is not None
        assert row["run_id"] == "run-abc"
        assert row["agent_id"] == "priya_blr"
        assert row["model"] == "openai/gpt-4o-mini"
        assert row["tokens_in"] == 842
        assert row["tokens_out"] == 47

    def test_complete_respects_daily_cap_before_call(
        self,
        llm_config: LLMConfig,
        usage_repo: UsageRepository,
        budgets: BudgetConfig,
    ) -> None:
        usage_repo.record_llm_usage(
            run_id="prior",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=2.00,
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            pytest.fail("HTTP should not be called when budget is exceeded")

        client = _make_client(
            llm_config,
            usage_repo,
            budgets,
            handler=httpx.MockTransport(handler),
        )
        with pytest.raises(BudgetExceededError, match="Daily"):
            client.complete(
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                run_id="run1",
                agent_id="alice",
            )

    def test_complete_respects_total_cap_before_call(
        self,
        llm_config: LLMConfig,
        usage_repo: UsageRepository,
        budgets: BudgetConfig,
    ) -> None:
        usage_repo.record_llm_usage(
            run_id="prior",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=50.00,
            created_at="2020-01-01T00:00:00Z",
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            pytest.fail("HTTP should not be called when budget is exceeded")

        client = _make_client(
            llm_config,
            usage_repo,
            budgets,
            handler=httpx.MockTransport(handler),
        )
        with pytest.raises(BudgetExceededError, match="Total"):
            client.complete(
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                run_id="run1",
                agent_id="alice",
            )

    def test_complete_allows_override_params(
        self,
        llm_config: LLMConfig,
        usage_repo: UsageRepository,
        budgets: BudgetConfig,
    ) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json=_chat_completion_response())

        client = _make_client(
            llm_config,
            usage_repo,
            budgets,
            handler=httpx.MockTransport(handler),
        )
        client.complete(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            model="openai/gpt-4o",
            temperature=0.2,
            max_tokens=128,
            run_id="run1",
            agent_id="alice",
        )
        body = captured["body"]
        assert isinstance(body, dict)
        assert body["model"] == "openai/gpt-4o"
        assert body["temperature"] == pytest.approx(0.2)
        assert body["max_tokens"] == 128


class TestPrompts:
    @pytest.fixture
    def config(self) -> object:
        return load_config(EXAMPLE_CONFIG)

    def test_assemble_extra_info_blocks(self, config: object) -> None:
        from hypeagent.config.schema import HypeagentConfig

        assert isinstance(config, HypeagentConfig)
        persona = config.personas["priya_blr"]
        blocks = assemble_extra_info_blocks(
            config,
            persona,
            knowledge_extra_infos=["Cast and format only."],
        )
        assert "## Global" in blocks
        assert "## Platform" in blocks
        assert "## LLM style" in blocks
        assert "## Run rules" in blocks
        assert "## Targeting" in blocks
        assert "## Persona extras" in blocks
        assert "## Knowledge" in blocks
        assert "Reality TV fan." in blocks
        assert "Cast and format only." in blocks

    def test_build_drafter_system_prompt(self, config: object) -> None:
        from hypeagent.config.schema import HypeagentConfig

        assert isinstance(config, HypeagentConfig)
        persona = config.personas["priya_blr"]
        prompt = build_drafter_system_prompt(
            config,
            persona,
            action_type=ActionType.REPLY,
            static_knowledge_summary="Reality TV predictions app.",
            tool_results="Episode 12: finale week.",
        )
        assert "Output ONLY the comment text" in prompt
        assert "## Persona" in prompt
        assert "Bangalore" in prompt
        assert "hinglish" in prompt
        assert "Reality TV predictions app." in prompt
        assert "Episode 12: finale week." in prompt
        assert "action_type: reply" in prompt

    def test_build_drafter_user_prompt(self) -> None:
        content = Content(
            id="post1",
            kind="post",
            author_id="u1",
            author_display="user123",
            body="I think X will get evicted this week",
            created_at=datetime.now(UTC),
            comment_count=1,
            metadata={},
        )
        parent = Comment(
            id="c1",
            content_id="post1",
            parent_id=None,
            author_id="u2",
            author_display="other_user",
            body="Same bro X is playing dirty",
            created_at=datetime.now(UTC),
            depth=0,
            metadata={},
        )
        thread = Thread(content=content, comments=[parent])
        prompt = build_drafter_user_prompt(
            thread,
            ActionType.REPLY,
            parent=parent,
        )
        assert "## Post" in prompt
        assert "user123" in prompt
        assert "I think X will get evicted" in prompt
        assert "@other_user: Same bro X is playing dirty" in prompt
        assert "## Reply target" in prompt
        assert "Write one reply." in prompt

    def test_format_thread_comments_empty(self) -> None:
        assert format_thread_comments([]) == "(no comments yet)"

    def test_format_thread_comments_nested_depth(self) -> None:
        comments = [
            Comment(
                id="c1",
                content_id="p1",
                parent_id=None,
                author_id="u1",
                author_display="alice",
                body="top level",
                created_at=datetime.now(UTC),
                depth=0,
                metadata={},
            ),
            Comment(
                id="c2",
                content_id="p1",
                parent_id="c1",
                author_id="u2",
                author_display="bob",
                body="nested reply",
                created_at=datetime.now(UTC),
                depth=1,
                metadata={},
            ),
        ]
        formatted = format_thread_comments(comments)
        assert "@alice: top level" in formatted
        assert "  @bob: nested reply" in formatted
