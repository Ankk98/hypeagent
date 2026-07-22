"""random_with_comments_last_24h targeting strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext
from hypeagent.targeting.base import TargetingStrategy


class RandomWithCommentsLast24hStrategy(TargetingStrategy):
    """Filter by recency and minimum comment count; caller picks uniformly at random."""

    name = "random_with_comments_last_24h"

    def apply(
        self,
        contents: list[Content],
        ctx: RunContext,
        params: dict[str, Any],
    ) -> list[Content]:
        _ = ctx
        since_hours = int(params.get("since_hours", 24))
        min_comment_count = int(params.get("min_comment_count", 1))
        cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
        return [
            content
            for content in contents
            if content.created_at >= cutoff and content.comment_count >= min_comment_count
        ]
