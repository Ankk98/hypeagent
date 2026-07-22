"""Unit tests for knowledge static loader and tools."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hypeagent.config.schema import HypeagentConfig, StaticKnowledgeItem, ToolConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.db.connection import Database
from hypeagent.db.repositories.agent_memory import AgentMemoryRepository
from hypeagent.knowledge.static import StaticKnowledgeLoader, truncate_text
from hypeagent.knowledge.tools import (
    MAX_TOOL_RESULT_CHARS,
    MAX_TOOL_ROUNDS,
    ToolExecutor,
    ToolLoadError,
    ToolRegistry,
    load_tool,
    parse_tool_request,
    truncate_tool_result,
    validate_tools,
)
from hypeagent.llm.client import LLMResponse
from hypeagent.models.run import RunContext, RunMode

EXAMPLE_DIR = Path("examples/reddit")
FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_config(**overrides: object) -> HypeagentConfig:
    data: dict[str, object] = {
        "version": 1,
        "name": "knowledge-test",
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
    data.update(overrides)
    return HypeagentConfig.model_validate(data)


def _run_context(db: Database | None = None) -> RunContext:
    config = _minimal_config()
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
        connector=object(),
        db=db or object(),
        logger=logging.getLogger("test"),
        llm_client=object(),
        budget_guard=object(),
    )


class TestTruncateText:
    def test_no_truncation_when_within_limit(self) -> None:
        assert truncate_text("hello world", 20) == "hello world"

    def test_truncates_with_ellipsis(self) -> None:
        assert truncate_text("abcdefghij", 7) == "abcd..."

    def test_strips_whitespace(self) -> None:
        assert truncate_text("  hello  ", 10) == "hello"


class TestStaticKnowledgeLoader:
    def test_loads_inline_content(self) -> None:
        loader = StaticKnowledgeLoader()
        item = StaticKnowledgeItem(inline="Reality TV predictions.", max_chars=100)
        assert loader.load_item(item) == "Reality TV predictions."

    def test_truncates_inline_content(self) -> None:
        loader = StaticKnowledgeLoader()
        item = StaticKnowledgeItem(inline="abcdefghijklmnop", max_chars=10)
        assert loader.load_item(item) == "abcdefg..."

    def test_loads_file_relative_to_base_dir(self, tmp_path: Path) -> None:
        brief = tmp_path / "brief.md"
        brief.write_text("Show bible content.", encoding="utf-8")
        loader = StaticKnowledgeLoader(base_dir=tmp_path)
        item = StaticKnowledgeItem(path="./brief.md", max_chars=500)
        assert loader.load_item(item) == "Show bible content."

    def test_summarize_combines_items_and_extra_info(self, tmp_path: Path) -> None:
        config = _minimal_config(
            knowledge={
                "static": [
                    {"inline": "Inline fact.", "max_chars": 100},
                    {
                        "path": str(EXAMPLE_DIR / "briefs/show_bible.md"),
                        "max_chars": 50,
                        "extra_info": "Cast and format only.",
                    },
                ],
            },
        )
        loader = StaticKnowledgeLoader(base_dir=Path.cwd())
        summary = loader.summarize(config)
        assert "Inline fact." in summary.summary
        assert "Show Bible" in summary.summary
        assert summary.extra_infos == ["Cast and format only."]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        loader = StaticKnowledgeLoader(base_dir=tmp_path)
        item = StaticKnowledgeItem(path="./missing.md", max_chars=100)
        with pytest.raises(FileNotFoundError, match="not found"):
            loader.load_item(item)


class TestParseToolRequest:
    def test_parses_full_json_body(self) -> None:
        parsed = parse_tool_request('{"tool": "recent_episode", "arguments": {"show_id": "s1"}}')
        assert parsed == ("recent_episode", {"show_id": "s1"})

    def test_parses_json_embedded_in_text(self) -> None:
        parsed = parse_tool_request('Need data first {"tool": "show_context", "arguments": {}}')
        assert parsed == ("show_context", {})

    def test_returns_none_for_plain_comment(self) -> None:
        assert parse_tool_request("Haan yaar same feeling") is None

    def test_defaults_missing_arguments_to_empty_dict(self) -> None:
        parsed = parse_tool_request('{"tool": "show_context"}')
        assert parsed == ("show_context", {})


class TestToolLoading:
    def test_loads_user_tool_from_tools_path(self) -> None:
        tool = load_tool(
            ToolConfig(
                name="show_context",
                module="tools.my_app.show_context",
                description="Show metadata.",
            ),
        )
        assert tool.name == "show_context"
        result = tool.run(_run_context(), {"show_id": "s1"})
        assert "Show s1" in result

    def test_validate_tools_reports_import_errors(self) -> None:
        errors = validate_tools(
            [
                ToolConfig(
                    name="bad",
                    module="tools.my_app.does_not_exist",
                    description="Missing module.",
                ),
            ],
        )
        assert len(errors) == 1
        assert "bad" in errors[0]

    def test_validate_tools_empty_list(self) -> None:
        assert validate_tools([]) == []


class TestToolRegistry:
    def test_execute_truncates_large_results(self) -> None:
        registry = ToolRegistry(
            [
                ToolConfig(
                    name="long_tool",
                    module="tests.fixtures.knowledge_tools.long_output",
                    description="Returns long text.",
                ),
            ],
        )
        ctx = _run_context()
        result = registry.execute(ctx, "long_tool", {})
        assert len(result) == MAX_TOOL_RESULT_CHARS

    def test_unknown_tool_raises(self) -> None:
        registry = ToolRegistry([])
        ctx = _run_context()
        with pytest.raises(ToolLoadError, match="Unknown tool"):
            registry.execute(ctx, "missing", {})


class TestBuiltinTools:
    def test_static_file_reads_path(self, tmp_path: Path) -> None:
        file_path = tmp_path / "notes.txt"
        file_path.write_text("Episode notes here.", encoding="utf-8")
        registry = ToolRegistry(
            [
                ToolConfig(
                    name="static_file",
                    module="hypeagent.knowledge.builtins.static_file",
                    description="Read file.",
                ),
            ],
        )
        ctx = _run_context()
        result = registry.execute(ctx, "static_file", {"path": str(file_path)})
        assert result == "Episode notes here."

    def test_short_term_memory_returns_recent_actions(self, tmp_path: Path) -> None:
        with Database(tmp_path / "mem.db") as db:
            repo = AgentMemoryRepository(db)
            repo.record(
                agent_id="alice",
                content_id="post1",
                action_type="reply",
                text_preview="First reply",
            )
            repo.record(
                agent_id="alice",
                content_id="post2",
                action_type="comment",
                text_preview="Second comment",
            )
            ctx = _run_context(db=db)
            registry = ToolRegistry(
                [
                    ToolConfig(
                        name="short_term_memory",
                        module="hypeagent.knowledge.builtins.short_term_memory",
                        description="Recent actions.",
                    ),
                ],
            )
            result = registry.execute(ctx, "short_term_memory", {"limit": 2})
            assert "post1" in result
            assert "post2" in result


class TestAgentMemoryRepository:
    def test_record_and_get_recent(self, tmp_path: Path) -> None:
        with Database(tmp_path / "mem.db") as db:
            repo = AgentMemoryRepository(db)
            repo.record(
                agent_id="alice",
                content_id="c1",
                action_type="comment",
                text_preview="Hello there",
                created_at="2026-07-22T10:00:00Z",
            )
            entries = repo.get_recent("alice", limit=5)
            assert len(entries) == 1
            assert entries[0].content_id == "c1"
            assert entries[0].text_preview == "Hello there"

    def test_get_recent_empty(self, tmp_path: Path) -> None:
        with Database(tmp_path / "mem.db") as db:
            repo = AgentMemoryRepository(db)
            assert repo.get_recent("nobody") == []


class TestToolExecutor:
    def test_completes_without_tool_request(self) -> None:
        llm = MagicMock()
        llm.complete.return_value = LLMResponse(
            content="Final comment text",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )
        registry = ToolRegistry(
            [
                ToolConfig(
                    name="show_context",
                    module="tools.my_app.show_context",
                    description="Show metadata.",
                ),
            ],
        )
        ctx = _run_context()
        executor = ToolExecutor(registry, llm)
        result = executor.complete_with_tools(
            ctx,
            system="System prompt",
            messages=[{"role": "user", "content": "Write comment"}],
        )
        assert result.final_text == "Final comment text"
        assert result.tool_calls == []
        assert llm.complete.call_count == 1

    def test_executes_at_most_two_tool_rounds(self) -> None:
        llm = MagicMock()
        llm.complete.side_effect = [
            LLMResponse(
                content='{"tool": "show_context", "arguments": {}}',
                model="openai/gpt-4o-mini",
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.001,
            ),
            LLMResponse(
                content='{"tool": "show_context", "arguments": {}}',
                model="openai/gpt-4o-mini",
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.001,
            ),
            LLMResponse(
                content="Done after tool rounds",
                model="openai/gpt-4o-mini",
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.001,
            ),
        ]
        registry = ToolRegistry(
            [
                ToolConfig(
                    name="show_context",
                    module="tools.my_app.show_context",
                    description="Show metadata.",
                ),
            ],
        )
        ctx = _run_context()
        executor = ToolExecutor(registry, llm)
        result = executor.complete_with_tools(
            ctx,
            system="System prompt",
            messages=[{"role": "user", "content": "Write comment"}],
        )
        assert result.final_text == "Done after tool rounds"
        assert len(result.tool_calls) == MAX_TOOL_ROUNDS
        assert llm.complete.call_count == MAX_TOOL_ROUNDS + 1


def test_truncate_tool_result() -> None:
    assert len(truncate_tool_result("a" * 3000)) == MAX_TOOL_RESULT_CHARS
