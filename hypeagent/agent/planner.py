"""Action type planning: comment vs reply from per-agent quotas."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hypeagent.config.schema import PerAgentConfig
from hypeagent.models.action import (
    ActionKind,
    ActionPayload,
    ActionSpec,
    ActionTarget,
    ActionTargetKind,
)
from hypeagent.models.content import Comment, Thread
from hypeagent.models.run import RunContext


@dataclass(frozen=True)
class PlannerDecision:
    """Chosen ActionSpec (payload.text filled after drafting)."""

    spec: ActionSpec


def _preview(text: str, max_len: int = 200) -> str:
    stripped = text.strip()
    if len(stripped) <= max_len:
        return stripped
    if max_len <= 3:
        return stripped[:max_len]
    return stripped[: max_len - 3].rstrip() + "..."


def _comment_spec(thread: Thread) -> ActionSpec:
    content = thread.content
    return ActionSpec(
        kind=ActionKind.COMMENT,
        content_id=content.id,
        target=ActionTarget(
            kind=ActionTargetKind.CONTENT,
            id=content.id,
            preview=_preview(content.body),
        ),
        payload=ActionPayload(),
    )


def _reply_spec(thread: Thread, parent: Comment) -> ActionSpec:
    return ActionSpec(
        kind=ActionKind.REPLY,
        content_id=thread.content.id,
        target=ActionTarget(
            kind=ActionTargetKind.COMMENT,
            id=parent.id,
            preview=_preview(parent.body),
        ),
        payload=ActionPayload(),
    )


class Planner:
    """Decide comment vs reply from quotas and thread state (§10.3)."""

    def decide(
        self,
        per_agent: PerAgentConfig,
        thread: Thread,
        ctx: RunContext,
    ) -> PlannerDecision | None:
        """
        v1 logic:
        - If replies quota > 0 and thread has comments → REPLY (random eligible parent)
        - Else if comments quota > 0 → COMMENT
        - Else skip (return None)

        When no eligible reply targets exist, fall back to COMMENT if that quota allows.
        """
        reply_depth_max = ctx.config.run.reply_depth_max
        connector = ctx.connector

        if per_agent.replies > 0 and thread.comments:
            eligible = [
                comment
                for comment in thread.comments
                if connector.can_reply(ctx, thread, comment, reply_depth_max)
            ]
            if eligible:
                return PlannerDecision(_reply_spec(thread, random.choice(eligible)))
            if per_agent.comments > 0:
                return PlannerDecision(_comment_spec(thread))
            return None

        if per_agent.comments > 0:
            return PlannerDecision(_comment_spec(thread))

        return None
