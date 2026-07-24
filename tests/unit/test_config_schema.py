"""Unit tests for config schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hypeagent.config.loader import ConfigError, load_config
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets import SecretsError, load_secrets, validate_account_refs

EXAMPLE_CONFIG = Path("examples/reddit/hypeagent.yaml")
EXAMPLE_SECRETS = Path("examples/reddit/secrets.example.yaml")

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "version": 1,
        "name": "test-run",
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
            "per_agent": {"comments": 0, "replies": 1},
        },
        "targeting": {"strategy": "recent"},
        "personas": {
            "alice": {
                "account": "alice",
                "brief": "Test persona.",
            },
        },
    }
    base.update(overrides)
    return base


class TestHypeagentConfig:
    def test_example_config_loads(self) -> None:
        config = load_config(EXAMPLE_CONFIG)
        assert config.name == "reddit-seed-example"
        assert config.run.agents == ["priya_blr", "rohan_del"]
        assert config.platform.subreddit == "test"

    def test_minimal_valid_config(self) -> None:
        config = HypeagentConfig.model_validate(_minimal_config())
        assert config.personas["alice"].account == "alice"

    def test_rejects_unknown_top_level_key(self) -> None:
        data = _minimal_config(unknown_field="nope")
        with pytest.raises(ValidationError, match="unknown_field"):
            HypeagentConfig.model_validate(data)

    def test_rejects_unknown_platform_key(self) -> None:
        data = _minimal_config()
        platform = dict(data["platform"])  # type: ignore[arg-type]
        platform["foo"] = "bar"
        data["platform"] = platform
        with pytest.raises(ValidationError, match="foo"):
            HypeagentConfig.model_validate(data)

    def test_rejects_unknown_targeting_strategy(self) -> None:
        data = _minimal_config()
        data["targeting"] = {"strategy": "not_a_strategy"}
        with pytest.raises(ValidationError, match="Unknown targeting strategy"):
            HypeagentConfig.model_validate(data)

    def test_rejects_run_agent_missing_from_personas(self) -> None:
        data = _minimal_config()
        data["run"] = {"agents": ["alice", "missing"], "per_agent": {"replies": 1}}
        with pytest.raises(ValidationError, match="unknown personas"):
            HypeagentConfig.model_validate(data)

    def test_rejects_static_knowledge_without_inline_or_path(self) -> None:
        data = _minimal_config()
        data["knowledge"] = {"static": [{"max_chars": 100}]}
        with pytest.raises(ValidationError, match="inline.*path"):
            HypeagentConfig.model_validate(data)

    def test_rejects_static_knowledge_with_both_inline_and_path(self) -> None:
        data = _minimal_config()
        data["knowledge"] = {
            "static": [{"inline": "x", "path": "./a.md", "max_chars": 100}],
        }
        with pytest.raises(ValidationError, match="inline.*path"):
            HypeagentConfig.model_validate(data)

    def test_rejects_total_budget_below_daily(self) -> None:
        data = _minimal_config()
        data["budgets"] = {"llm_daily_usd": 10.0, "llm_total_usd": 5.0}
        with pytest.raises(ValidationError, match="llm_total_usd"):
            HypeagentConfig.model_validate(data)

    def test_rejects_empty_run_agents(self) -> None:
        data = _minimal_config()
        data["run"] = {"agents": [], "per_agent": {"replies": 1}}
        with pytest.raises(ValidationError):
            HypeagentConfig.model_validate(data)

    def test_rejects_missing_config_file(self) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/hypeagent.yaml")

    def test_all_targeting_strategies_accepted(self) -> None:
        for strategy in (
            "random_with_comments_last_24h",
            "recent",
            "oldest_unanswered",
            "allowlist",
        ):
            data = _minimal_config()
            data["targeting"] = {"strategy": strategy}
            config = HypeagentConfig.model_validate(data)
            assert config.targeting.strategy == strategy

    def test_accepts_reactions_and_engagement(self) -> None:
        data = _minimal_config()
        data["run"] = {
            "agents": ["alice"],
            "per_agent": {"comments": 0, "replies": 0, "reactions": 1},
            "action_priority": ["reaction", "comment", "reply"],
        }
        data["engagement"] = {
            "reactions": {
                "enabled": True,
                "targets": ["content"],
                "types": ["agree", "like"],
                "strategy": "weighted",
                "weights": {"agree": 0.7, "like": 0.3},
            }
        }
        config = HypeagentConfig.model_validate(data)
        assert config.run.per_agent.reactions == 1
        assert config.engagement.reactions.strategy == "weighted"
        assert config.reactions_requested() is True

    def test_default_engagement_disabled(self) -> None:
        config = HypeagentConfig.model_validate(_minimal_config())
        assert config.run.per_agent.reactions == 0
        assert config.engagement.reactions.enabled is False
        assert config.reactions_requested() is False


class TestSecrets:
    def test_example_secrets_load(self) -> None:
        secrets = load_secrets(EXAMPLE_SECRETS)
        assert set(secrets.accounts) == {"priya_blr", "rohan_del"}

    def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(SecretsError, match="api_key"):
            load_secrets(FIXTURES / "secrets_empty_key.yaml")

    def test_rejects_unknown_account_key(self) -> None:
        data = _minimal_config()
        config = HypeagentConfig.model_validate(data)
        secrets = load_secrets(EXAMPLE_SECRETS)
        errors = validate_account_refs(
            {"ghost": config.personas["alice"].model_copy(update={"account": "nobody"})},
            secrets,
        )
        assert len(errors) == 1
        assert "nobody" in errors[0]

    def test_validate_account_refs_passes_for_example(self) -> None:
        config = load_config(EXAMPLE_CONFIG)
        secrets = load_secrets(EXAMPLE_SECRETS)
        assert validate_account_refs(config.personas, secrets) == []
