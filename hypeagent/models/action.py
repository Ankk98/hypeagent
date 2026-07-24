"""Agent action models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class ActionKind(StrEnum):
    """Canonical engagement action kinds."""

    COMMENT = "comment"
    REPLY = "reply"
    REACT = "react"
    VOTE = "vote"


# Backward-compatible alias during migration to ActionKind.
ActionType = ActionKind


class ActionTargetKind(StrEnum):
    """What an action engages with."""

    CONTENT = "content"
    COMMENT = "comment"


@dataclass(frozen=True)
class ActionTarget:
    """Address of the entity being engaged with."""

    kind: ActionTargetKind
    id: str
    preview: str | None = None


@dataclass(frozen=True)
class ActionPayload:
    """Kind-specific body. Set the field that matches ActionKind."""

    text: str | None = None  # COMMENT / REPLY
    reaction_type: str | None = None  # REACT — platform vocabulary
    vote_value: int | None = None  # VOTE — e.g. 1 / -1 / 0


@dataclass(frozen=True)
class ActionSpec:
    """Platform-agnostic description of one engagement action."""

    kind: ActionKind
    content_id: str
    target: ActionTarget
    payload: ActionPayload
    rationale: str | None = None


@dataclass(frozen=True)
class PublishResult:
    """Result of connector.execute()."""

    platform_object_id: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    result_preview: str
    duration_ms: int


@dataclass
class ProposedAction:
    run_id: str
    agent_id: str
    account_id: str
    action_type: ActionType
    content_id: str
    content_body_preview: str
    parent_comment_id: str | None
    parent_comment_preview: str | None
    draft_text: str
    targeting_strategy: str
    llm_model: str
    llm_tokens_in: int
    llm_tokens_out: int
    llm_cost_usd: float
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_action_spec(self) -> ActionSpec:
        """Build an ActionSpec for connector.execute() from persisted fields."""
        if self.action_type == ActionKind.REPLY:
            target = ActionTarget(
                kind=ActionTargetKind.COMMENT,
                id=self.parent_comment_id or "",
                preview=self.parent_comment_preview,
            )
        else:
            target = ActionTarget(
                kind=ActionTargetKind.CONTENT,
                id=self.content_id,
                preview=self.content_body_preview,
            )
        return ActionSpec(
            kind=ActionKind(self.action_type),
            content_id=self.content_id,
            target=target,
            payload=ActionPayload(text=self.draft_text),
        )


@dataclass
class PublishedAction:
    proposed: ProposedAction
    platform_comment_id: str
    published_at: datetime
    approved_by: Literal["auto", "human", "dry-run"]
