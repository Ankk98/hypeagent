"""recent targeting strategy."""

from __future__ import annotations

from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext
from hypeagent.targeting.base import TargetingStrategy


class RecentStrategy(TargetingStrategy):
    """Return the newest post that already has comments."""

    name = "recent"

    def apply(
        self,
        contents: list[Content],
        ctx: RunContext,
        params: dict[str, Any],
    ) -> list[Content]:
        _ = (ctx, params)
        with_comments = [content for content in contents if content.comment_count >= 1]
        if not with_comments:
            return []
        newest = max(with_comments, key=lambda content: content.created_at)
        return [newest]
