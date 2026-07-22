"""Action type planning: comment vs reply from per-agent quotas."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hypeagent.config.schema import PerAgentConfig
from hypeagent.models.action import ActionType
from hypeagent.models.content import Comment, Thread
from hypeagent.models.run import RunContext


@dataclass(frozen=True)
class PlannerDecision:
    """Chosen action type and optional reply parent."""

    action_type: ActionType
    parent: Comment | None


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
                return PlannerDecision(ActionType.REPLY, random.choice(eligible))
            if per_agent.comments > 0:
                return PlannerDecision(ActionType.COMMENT, None)
            return None

        if per_agent.comments > 0:
            return PlannerDecision(ActionType.COMMENT, None)

        return None
