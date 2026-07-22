"""oldest_unanswered targeting strategy."""

from __future__ import annotations

from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext
from hypeagent.targeting.base import TargetingStrategy


def agent_comment_count(content: Content) -> int:
    """Return how many comments the current agent account has on this content."""
    value = content.metadata.get("agent_comment_count")
    if value is None:
        return 0
    return int(value)


class OldestUnansweredStrategy(TargetingStrategy):
    """Pick the oldest post with the fewest comments from the agent account."""

    name = "oldest_unanswered"

    def apply(
        self,
        contents: list[Content],
        ctx: RunContext,
        params: dict[str, Any],
    ) -> list[Content]:
        _ = (ctx, params)
        if not contents:
            return []
        min_count = min(agent_comment_count(content) for content in contents)
        unanswered = [
            content for content in contents if agent_comment_count(content) == min_count
        ]
        oldest = min(unanswered, key=lambda content: content.created_at)
        return [oldest]
