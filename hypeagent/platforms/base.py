"""Platform connector abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from hypeagent.config.schema import HttpConfig, PlatformConfig, TargetingConfig
from hypeagent.config.secrets_schema import AccountSecret
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext


class PlatformError(Exception):
    """Raised when a platform API call fails."""


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
