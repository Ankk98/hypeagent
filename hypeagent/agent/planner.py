"""Action kind planning from quotas, capabilities, and engagement config."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hypeagent.agent.reactions import choose_reaction_type, resolve_allowed_types
from hypeagent.config.schema import (
    DEFAULT_ACTION_PRIORITY,
    ActionPriorityName,
    PerAgentConfig,
)
from hypeagent.models.action import (
    ActionKind,
    ActionPayload,
    ActionSpec,
    ActionTarget,
    ActionTargetKind,
)
from hypeagent.models.content import Comment, Thread
from hypeagent.models.run import RunContext
from hypeagent.platforms.base import ReactionCapability

_PRIORITY_TO_KIND: dict[ActionPriorityName, ActionKind] = {
    "reply": ActionKind.REPLY,
    "comment": ActionKind.COMMENT,
    "reaction": ActionKind.REACT,
    "vote": ActionKind.VOTE,
}

_TARGET_NAME_TO_KIND = {
    "content": ActionTargetKind.CONTENT,
    "comment": ActionTargetKind.COMMENT,
}


@dataclass(frozen=True)
class PlannerDecision:
    """Chosen ActionSpec (payload filled after drafting / reaction choose)."""

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


def _react_spec(
    thread: Thread,
    target: ActionTarget,
    reaction_type: str,
) -> ActionSpec:
    return ActionSpec(
        kind=ActionKind.REACT,
        content_id=thread.content.id,
        target=target,
        payload=ActionPayload(reaction_type=reaction_type),
    )


class Planner:
    """Decide action kind from quotas ∩ capabilities ∩ engagement config."""

    def decide(
        self,
        per_agent: PerAgentConfig,
        thread: Thread,
        ctx: RunContext,
    ) -> PlannerDecision | None:
        """
        Try kinds in action_priority order (default: reply → comment → reaction → vote).

        REPLY/COMMENT keep prior eligibility rules. REACT uses engagement config and
        connector reaction capabilities. VOTE is reserved for a later phase.
        """
        priority = ctx.config.run.action_priority or list(DEFAULT_ACTION_PRIORITY)
        for name in priority:
            kind = _PRIORITY_TO_KIND[name]
            if kind == ActionKind.REPLY:
                decision = self._try_reply(per_agent, thread, ctx)
            elif kind == ActionKind.COMMENT:
                decision = self._try_comment(per_agent, thread)
            elif kind == ActionKind.REACT:
                decision = self._try_react(per_agent, thread, ctx)
            else:
                decision = None
            if decision is not None:
                return decision
        return None

    def _try_reply(
        self,
        per_agent: PerAgentConfig,
        thread: Thread,
        ctx: RunContext,
    ) -> PlannerDecision | None:
        if per_agent.replies <= 0 or not thread.comments:
            return None
        reply_depth_max = ctx.config.run.reply_depth_max
        connector = ctx.connector
        eligible = [
            comment
            for comment in thread.comments
            if connector.can_reply(ctx, thread, comment, reply_depth_max)
        ]
        if not eligible:
            return None
        return PlannerDecision(_reply_spec(thread, random.choice(eligible)))

    def _try_comment(
        self,
        per_agent: PerAgentConfig,
        thread: Thread,
    ) -> PlannerDecision | None:
        if per_agent.comments <= 0:
            return None
        return PlannerDecision(_comment_spec(thread))

    def _try_react(
        self,
        per_agent: PerAgentConfig,
        thread: Thread,
        ctx: RunContext,
    ) -> PlannerDecision | None:
        if per_agent.reactions <= 0:
            return None

        caps = ctx.connector.capabilities().reactions
        if caps is None:
            return None

        reaction_cfg = ctx.config.engagement.reactions
        allowed_types = resolve_allowed_types(reaction_cfg, caps.allowed_types)
        if not allowed_types:
            return None

        targets = self._reaction_targets(thread, ctx, caps)
        if not targets:
            return None

        target = random.choice(targets)
        reaction_type = choose_reaction_type(
            allowed_types=allowed_types,
            reaction_cfg=reaction_cfg,
            persona=ctx.persona,
            thread=thread,
            llm_client=ctx.llm_client if reaction_cfg.strategy == "llm_choose" else None,
            run_id=ctx.run_id,
            agent_id=ctx.agent_id,
        )
        if reaction_type is None:
            return None
        return PlannerDecision(_react_spec(thread, target, reaction_type))

    def _reaction_targets(
        self,
        thread: Thread,
        ctx: RunContext,
        caps: ReactionCapability,
    ) -> list[ActionTarget]:
        reaction_cfg = ctx.config.engagement.reactions
        avoid_authors = set(reaction_cfg.avoid_content_author_ids)
        candidates: list[ActionTarget] = []

        for target_name in reaction_cfg.targets:
            kind = _TARGET_NAME_TO_KIND[target_name]
            if kind not in caps.target_kinds:
                continue
            if kind == ActionTargetKind.CONTENT:
                if thread.content.author_id in avoid_authors:
                    continue
                target = ActionTarget(
                    kind=ActionTargetKind.CONTENT,
                    id=thread.content.id,
                    preview=_preview(thread.content.body),
                )
                if self._reaction_target_ok(ctx, target, reaction_cfg.skip_if_already_reacted):
                    candidates.append(target)
            elif kind == ActionTargetKind.COMMENT:
                for comment in thread.comments:
                    if comment.author_id in avoid_authors:
                        continue
                    target = ActionTarget(
                        kind=ActionTargetKind.COMMENT,
                        id=comment.id,
                        preview=_preview(comment.body),
                    )
                    if self._reaction_target_ok(
                        ctx, target, reaction_cfg.skip_if_already_reacted
                    ):
                        candidates.append(target)
        return candidates

    def _reaction_target_ok(
        self,
        ctx: RunContext,
        target: ActionTarget,
        skip_if_already: bool,
    ) -> bool:
        if not skip_if_already:
            return True
        engagement = ctx.connector.current_engagement(ctx, target)
        my_reaction = engagement.get("myReaction")
        return not my_reaction
