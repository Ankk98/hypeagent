"""allowlist targeting strategy."""

from __future__ import annotations

from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext
from hypeagent.targeting.base import TargetingStrategy


class AllowlistStrategy(TargetingStrategy):
    """Restrict candidates to an explicit list of content IDs."""

    name = "allowlist"

    def apply(
        self,
        contents: list[Content],
        ctx: RunContext,
        params: dict[str, Any],
    ) -> list[Content]:
        _ = ctx
        raw_ids = params.get("content_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return []
        allowlist = [str(content_id) for content_id in raw_ids]
        by_id = {content.id: content for content in contents}
        return [by_id[content_id] for content_id in allowlist if content_id in by_id]
