"""Agent action models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class ActionType(StrEnum):
    COMMENT = "comment"
    REPLY = "reply"


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


@dataclass
class PublishedAction:
    proposed: ProposedAction
    platform_comment_id: str
    published_at: datetime
    approved_by: Literal["auto", "human", "dry-run"]
