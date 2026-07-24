"""Platform connector abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from hypeagent.config.schema import HttpConfig, PlatformConfig, TargetingConfig
from hypeagent.config.secrets_schema import AccountSecret
from hypeagent.models.action import (
    ActionKind,
    ActionSpec,
    ActionTarget,
    ActionTargetKind,
    PublishResult,
)
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext


class PlatformError(Exception):
    """Raised when a platform API call fails."""


@dataclass(frozen=True)
class ReactionCapability:
    """Connector-declared reaction (or vote) support."""

    target_kinds: frozenset[ActionTargetKind]
    allowed_types: frozenset[str]
    mode: Literal["toggle", "set", "additive"]
    max_per_entity: int | None = 1


@dataclass(frozen=True)
class PlatformCapabilities:
    """What engagement kinds a connector can publish."""

    text_comment: bool = True
    text_reply: bool = True
    reactions: ReactionCapability | None = None
    votes: ReactionCapability | None = None


class PlatformConnector(ABC):
    """Abstract connector mapping platform data to canonical models."""

    name: str

    def __init__(
        self,
        platform_config: PlatformConfig,
        account: AccountSecret,
        http: HttpConfig,
    ) -> None:
        self._platform_config = platform_config
        self._account = account
        self._http_config = http

    @abstractmethod
    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        """Return candidate posts (v1: kind=post only)."""

    @abstractmethod
    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        """Return content and all comments (flat list with parent_id)."""

    @abstractmethod
    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        """POST comment/reply as current account. Raises PlatformError on failure."""

    def capabilities(self) -> PlatformCapabilities:
        """Default: comments + replies only (today's Reddit behavior)."""
        return PlatformCapabilities()

    def publish_reaction(
        self,
        ctx: RunContext,
        target: ActionTarget,
        reaction_type: str,
    ) -> PublishResult:
        """Publish a reaction. Override when capabilities().reactions is non-null."""
        _ = ctx, target, reaction_type
        msg = (
            f"Connector {self.name!r} advertises reactions but does not implement "
            "publish_reaction()"
        )
        raise PlatformError(msg)

    def execute(self, ctx: RunContext, spec: ActionSpec) -> PublishResult:
        """Publish an ActionSpec. Default routes COMMENT/REPLY/REACT to helpers."""
        if spec.kind in (ActionKind.COMMENT, ActionKind.REPLY):
            text = spec.payload.text
            if not text:
                msg = f"ActionSpec kind={spec.kind.value} requires payload.text"
                raise PlatformError(msg)
            parent_comment_id = (
                spec.target.id if spec.kind == ActionKind.REPLY else None
            )
            if spec.kind == ActionKind.REPLY and not parent_comment_id:
                msg = "ActionSpec kind=reply requires target.id (parent comment)"
                raise PlatformError(msg)
            comment = self.publish_comment(
                ctx,
                spec.content_id,
                text,
                parent_comment_id,
            )
            return PublishResult(
                platform_object_id=comment.id,
                raw={"comment_id": comment.id},
            )
        caps = self.capabilities()
        if spec.kind == ActionKind.REACT:
            if caps.reactions is None:
                msg = f"Connector {self.name!r} does not support reactions"
                raise PlatformError(msg)
            reaction_type = spec.payload.reaction_type
            if not reaction_type:
                msg = "ActionSpec kind=react requires payload.reaction_type"
                raise PlatformError(msg)
            if reaction_type not in caps.reactions.allowed_types:
                msg = (
                    f"Reaction type {reaction_type!r} is not in connector "
                    f"{self.name!r} allowlist"
                )
                raise PlatformError(msg)
            if spec.target.kind not in caps.reactions.target_kinds:
                msg = (
                    f"Connector {self.name!r} cannot react to target kind "
                    f"{spec.target.kind.value!r}"
                )
                raise PlatformError(msg)
            return self.publish_reaction(ctx, spec.target, reaction_type)
        if spec.kind == ActionKind.VOTE and caps.votes is None:
            msg = f"Connector {self.name!r} does not support votes"
            raise PlatformError(msg)
        msg = f"Unsupported action kind for execute(): {spec.kind.value}"
        raise PlatformError(msg)

    def current_engagement(
        self,
        ctx: RunContext,
        target: ActionTarget,
    ) -> dict[str, Any]:
        """Return current user engagement on a target (e.g. myReaction). Default {}."""
        _ = ctx, target
        return {}

    def can_reply(
        self,
        ctx: RunContext,
        thread: Thread,
        parent: Comment | None,
        reply_depth_max: int,
    ) -> bool:
        """Default: depth check via parent chain. Override for membership rules."""
        if parent is None:
            return True
        return parent.depth < reply_depth_max

    def filter_candidates(
        self,
        ctx: RunContext,
        contents: list[Content],
        strategy: TargetingConfig,
    ) -> list[Content]:
        """Default: delegate to targeting registry."""
        from hypeagent.targeting.registry import apply_strategy

        return apply_strategy(strategy.strategy, contents, ctx, strategy.params)
