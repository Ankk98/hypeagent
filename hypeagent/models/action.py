"""Agent action models."""

from __future__ import annotations

import json
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

    def to_json(self) -> str:
        """Serialize payload fields for SQLite persistence."""
        return json.dumps(
            {
                "text": self.text,
                "reaction_type": self.reaction_type,
                "vote_value": self.vote_value,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str | None) -> ActionPayload:
        """Deserialize payload_json from SQLite."""
        if not raw:
            return cls()
        data = json.loads(raw)
        return cls(
            text=data.get("text"),
            reaction_type=data.get("reaction_type"),
            vote_value=data.get("vote_value"),
        )


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
    reaction_type: str | None = None
    vote_value: int | None = None
    target_kind: ActionTargetKind | None = None
    target_id: str | None = None
    payload_json: str | None = None

    def to_action_spec(self) -> ActionSpec:
        """Build an ActionSpec for connector.execute() from persisted fields."""
        if self.action_type == ActionKind.REACT:
            payload = ActionPayload.from_json(self.payload_json)
            if self.reaction_type and not payload.reaction_type:
                payload = ActionPayload(reaction_type=self.reaction_type)
            target_kind = self.target_kind or ActionTargetKind.CONTENT
            target_id = self.target_id or self.content_id
            preview = (
                self.parent_comment_preview
                if target_kind == ActionTargetKind.COMMENT
                else self.content_body_preview
            )
            return ActionSpec(
                kind=ActionKind.REACT,
                content_id=self.content_id,
                target=ActionTarget(kind=target_kind, id=target_id, preview=preview),
                payload=payload,
            )
        if self.action_type == ActionKind.VOTE:
            payload = ActionPayload.from_json(self.payload_json)
            if self.vote_value is not None and payload.vote_value is None:
                payload = ActionPayload(vote_value=self.vote_value)
            target_kind = self.target_kind or ActionTargetKind.CONTENT
            target_id = self.target_id or self.content_id
            preview = (
                self.parent_comment_preview
                if target_kind == ActionTargetKind.COMMENT
                else self.content_body_preview
            )
            return ActionSpec(
                kind=ActionKind.VOTE,
                content_id=self.content_id,
                target=ActionTarget(kind=target_kind, id=target_id, preview=preview),
                payload=payload,
            )
        if self.action_type == ActionKind.REPLY:
            return ActionSpec(
                kind=ActionKind.REPLY,
                content_id=self.content_id,
                target=ActionTarget(
                    kind=ActionTargetKind.COMMENT,
                    id=self.parent_comment_id or "",
                    preview=self.parent_comment_preview,
                ),
                payload=ActionPayload(text=self.draft_text),
            )
        return ActionSpec(
            kind=ActionKind(self.action_type),
            content_id=self.content_id,
            target=ActionTarget(
                kind=ActionTargetKind.CONTENT,
                id=self.content_id,
                preview=self.content_body_preview,
            ),
            payload=ActionPayload(text=self.draft_text),
        )

    def display_preview(self) -> str:
        """Short label for logs / memory (draft text, reaction type, or vote)."""
        if self.action_type == ActionKind.REACT:
            return self.reaction_type or ""
        if self.action_type == ActionKind.VOTE:
            if self.vote_value is None:
                return ""
            return str(self.vote_value)
        return self.draft_text


@dataclass
class PublishedAction:
    proposed: ProposedAction
    platform_comment_id: str
    published_at: datetime
    approved_by: Literal["auto", "human", "dry-run"]
