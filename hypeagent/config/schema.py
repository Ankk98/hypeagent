"""Pydantic models for hypeagent.yaml configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TARGETING_STRATEGIES = frozenset(
    {
        "random_with_comments_last_24h",
        "recent",
        "oldest_unanswered",
        "allowlist",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformConfig(StrictModel):
    connector: str
    base_url: str
    user_agent: str
    subreddit: str | None = None
    extra_info: str | None = None


class HttpConfig(StrictModel):
    timeout_seconds: int = 30
    retry_count: int = 2


class LLMConfig(StrictModel):
    provider: Literal["openrouter", "openai_compatible"] = "openrouter"
    base_url: str
    model: str
    temperature: float = 0.9
    max_tokens: int = 256
    extra_info: str | None = None


class BudgetConfig(StrictModel):
    llm_daily_usd: float = Field(gt=0)
    llm_total_usd: float = Field(gt=0)
    max_actions_per_run: int = Field(default=50, ge=1)

    @model_validator(mode="after")
    def total_gte_daily(self) -> BudgetConfig:
        if self.llm_total_usd < self.llm_daily_usd:
            msg = "llm_total_usd must be >= llm_daily_usd"
            raise ValueError(msg)
        return self


class PerAgentConfig(StrictModel):
    comments: int = Field(default=0, ge=0)
    replies: int = Field(default=1, ge=0)
    reactions: int = Field(default=0, ge=0)


ActionPriorityName = Literal["reply", "comment", "reaction", "vote"]
DEFAULT_ACTION_PRIORITY: tuple[ActionPriorityName, ...] = (
    "reply",
    "comment",
    "reaction",
    "vote",
)
ReactionTargetName = Literal["content", "comment"]
ReactionStrategyName = Literal["weighted", "random", "llm_choose", "persona_affinity"]


def _default_reaction_targets() -> list[ReactionTargetName]:
    return ["content"]


class ReactionsEngagementConfig(StrictModel):
    enabled: bool = False
    targets: list[ReactionTargetName] = Field(default_factory=_default_reaction_targets)
    types: list[str] | None = None
    strategy: ReactionStrategyName = "weighted"
    weights: dict[str, float] = Field(default_factory=dict)
    skip_if_already_reacted: bool = True
    avoid_content_author_ids: list[str] = Field(default_factory=list)

    @field_validator("targets")
    @classmethod
    def non_empty_targets(cls, value: list[ReactionTargetName]) -> list[ReactionTargetName]:
        if not value:
            msg = "engagement.reactions.targets must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("types")
    @classmethod
    def non_empty_types(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not value:
            msg = "engagement.reactions.types must be non-empty when set"
            raise ValueError(msg)
        return value


class EngagementConfig(StrictModel):
    reactions: ReactionsEngagementConfig = Field(default_factory=ReactionsEngagementConfig)


class RunConfig(StrictModel):
    agents: list[str] = Field(min_length=1)
    per_agent: PerAgentConfig
    reply_depth_max: int = Field(default=2, ge=0)
    action_priority: list[ActionPriorityName] | None = None
    extra_info: str | None = None


class TargetingConfig(StrictModel):
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    extra_info: str | None = None

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        if value not in TARGETING_STRATEGIES:
            strategies = ", ".join(sorted(TARGETING_STRATEGIES))
            msg = f"Unknown targeting strategy {value!r}; expected one of: {strategies}"
            raise ValueError(msg)
        return value


class PersonaConfig(StrictModel):
    account: str
    city: str | None = None
    languages: list[str] | None = None
    brief: str
    extra_info: str | None = None


class StaticKnowledgeItem(StrictModel):
    inline: str | None = None
    path: str | None = None
    max_chars: int = Field(default=500, ge=1)
    extra_info: str | None = None

    @model_validator(mode="after")
    def require_inline_or_path(self) -> StaticKnowledgeItem:
        if bool(self.inline) == bool(self.path):
            msg = "Each static knowledge item must have exactly one of 'inline' or 'path'"
            raise ValueError(msg)
        return self


class ToolConfig(StrictModel):
    name: str
    module: str
    description: str


class KnowledgeConfig(StrictModel):
    static: list[StaticKnowledgeItem] = Field(default_factory=list)
    tools: list[ToolConfig] = Field(default_factory=list)


class LoggingConfig(StrictModel):
    level: Literal["debug", "info", "warning", "error"] = "info"
    file: str | None = None
    console: bool = True


class HypeagentConfig(StrictModel):
    version: Literal[1] = 1
    name: str
    extra_info: str | None = None
    platform: PlatformConfig
    http: HttpConfig = Field(default_factory=HttpConfig)
    llm: LLMConfig
    budgets: BudgetConfig
    run: RunConfig
    targeting: TargetingConfig
    personas: dict[str, PersonaConfig]
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    engagement: EngagementConfig = Field(default_factory=EngagementConfig)

    @model_validator(mode="after")
    def validate_run_agents(self) -> HypeagentConfig:
        missing = [agent_id for agent_id in self.run.agents if agent_id not in self.personas]
        if missing:
            msg = f"run.agents references unknown personas: {', '.join(missing)}"
            raise ValueError(msg)
        return self

    def reactions_requested(self) -> bool:
        """True when config asks to publish reactions this run."""
        return self.run.per_agent.reactions > 0 or self.engagement.reactions.enabled


# Alias used in the implementation plan.
hypeagentConfig = HypeagentConfig
