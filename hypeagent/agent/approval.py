"""Interactive approval prompts before publishing (§10.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from hypeagent.agent.reactions import resolve_allowed_types
from hypeagent.agent.votes import resolve_allowed_values
from hypeagent.models.action import ActionKind, ActionTargetKind, ProposedAction
from hypeagent.models.run import RunContext


class ApprovalQuitError(Exception):
    """Raised when the user quits the run during an approval prompt."""


class ApprovalDecision(StrEnum):
    PUBLISH = "publish"
    SKIP = "skip"
    EDIT = "edit"
    QUIT = "quit"


@dataclass(frozen=True)
class ApprovalResponse:
    decision: ApprovalDecision
    draft_text: str
    reaction_type: str | None = None
    vote_value: int | None = None


class ApprovalPrompt:
    """Prompt founder to approve, skip, edit, or quit before publishing."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._input = input_fn or input
        self._output = output_fn or print

    def prompt(self, ctx: RunContext, proposed: ProposedAction) -> ApprovalResponse:
        """Show previews and return the user's decision."""
        draft_text = proposed.draft_text
        reaction_type = proposed.reaction_type
        vote_value = proposed.vote_value
        while True:
            self._render(ctx, proposed, draft_text, reaction_type, vote_value)
            choice = self._read_choice()
            if choice == ApprovalDecision.PUBLISH:
                return ApprovalResponse(
                    ApprovalDecision.PUBLISH,
                    draft_text,
                    reaction_type=reaction_type,
                    vote_value=vote_value,
                )
            if choice == ApprovalDecision.SKIP:
                return ApprovalResponse(
                    ApprovalDecision.SKIP,
                    draft_text,
                    reaction_type=reaction_type,
                    vote_value=vote_value,
                )
            if choice == ApprovalDecision.QUIT:
                return ApprovalResponse(
                    ApprovalDecision.QUIT,
                    draft_text,
                    reaction_type=reaction_type,
                    vote_value=vote_value,
                )
            if proposed.action_type == ActionKind.REACT:
                reaction_type = self._edit_reaction(ctx, reaction_type or "")
            elif proposed.action_type == ActionKind.VOTE:
                vote_value = self._edit_vote(ctx, vote_value)
            else:
                draft_text = self._edit_draft(draft_text)

    def _render(
        self,
        ctx: RunContext,
        proposed: ProposedAction,
        draft_text: str,
        reaction_type: str | None,
        vote_value: int | None,
    ) -> None:
        persona = ctx.persona
        agent_bits: list[str] = []
        if persona.city:
            agent_bits.append(persona.city)
        if persona.languages:
            agent_bits.append(", ".join(persona.languages))
        agent_suffix = f" ({', '.join(agent_bits)})" if agent_bits else ""

        lines = [
            "",
            f"Agent: {proposed.agent_id}{agent_suffix}",
            f"Action: {proposed.action_type.value.upper()}",
            "",
            f"Post preview ({proposed.content_id}):",
            f'  "{proposed.content_body_preview}"',
        ]
        if proposed.action_type == ActionKind.REPLY and proposed.parent_comment_preview:
            lines.extend(
                [
                    "",
                    "Replying to:",
                    f'  "{proposed.parent_comment_preview}"',
                ]
            )
        if proposed.action_type == ActionKind.REACT:
            target_label, target_preview = _target_bits(proposed)
            lines.extend(
                [
                    "",
                    f"Target: {target_label} {proposed.target_id or proposed.content_id}",
                    f'Preview: "{target_preview}"',
                    "",
                    f"Reaction: {reaction_type or '(none)'}",
                    "",
                    "Publish? [Y/n/e/q] (e=edit reaction type, q=quit run)",
                ]
            )
        elif proposed.action_type == ActionKind.VOTE:
            target_label, target_preview = _target_bits(proposed)
            lines.extend(
                [
                    "",
                    f"Target: {target_label} {proposed.target_id or proposed.content_id}",
                    f'Preview: "{target_preview}"',
                    "",
                    f"Vote: {vote_value if vote_value is not None else '(none)'}",
                    "",
                    "Publish? [Y/n/e/q] (e=edit vote value, q=quit run)",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Draft:",
                    f'  "{draft_text}"',
                    "",
                    "Publish? [Y/n/e/q] (e=edit draft, q=quit run)",
                ]
            )
        self._output("\n".join(lines))

    def _read_choice(self) -> ApprovalDecision:
        while True:
            raw = self._input("").strip().lower()
            if raw in {"", "y", "yes"}:
                return ApprovalDecision.PUBLISH
            if raw in {"n", "no"}:
                return ApprovalDecision.SKIP
            if raw == "e":
                return ApprovalDecision.EDIT
            if raw == "q":
                return ApprovalDecision.QUIT
            self._output("Invalid choice. Enter Y, n, e, or q.")

    def _edit_draft(self, current: str) -> str:
        self._output("Enter new draft (blank line keeps current):")
        updated = self._input("").strip()
        return updated if updated else current

    def _edit_reaction(self, ctx: RunContext, current: str) -> str:
        allowed = _allowed_reaction_types(ctx)
        allow_hint = ", ".join(allowed) if allowed else "(connector allowlist)"
        self._output(f"Enter reaction type [{allow_hint}] (blank keeps current):")
        updated = self._input("").strip()
        if not updated:
            return current
        if allowed and updated not in allowed:
            # case-insensitive match
            lowered = {t.lower(): t for t in allowed}
            matched = lowered.get(updated.lower())
            if matched is None:
                self._output(f"Invalid type {updated!r}; keeping {current!r}.")
                return current
            return matched
        return updated

    def _edit_vote(self, ctx: RunContext, current: int | None) -> int | None:
        allowed = _allowed_vote_values(ctx)
        allow_hint = ", ".join(str(v) for v in allowed) if allowed else "-1, 0, 1"
        self._output(f"Enter vote value [{allow_hint}] (blank keeps current):")
        updated = self._input("").strip()
        if not updated:
            return current
        try:
            value = int(updated)
        except ValueError:
            self._output(f"Invalid vote {updated!r}; keeping {current!r}.")
            return current
        if allowed and value not in allowed:
            self._output(f"Invalid vote {value!r}; keeping {current!r}.")
            return current
        return value


def _target_bits(proposed: ProposedAction) -> tuple[str, str]:
    target_label = "post"
    target_preview = proposed.content_body_preview
    if proposed.target_kind == ActionTargetKind.COMMENT:
        target_label = "comment"
        if proposed.parent_comment_preview:
            target_preview = proposed.parent_comment_preview
    return target_label, target_preview


def _allowed_reaction_types(ctx: RunContext) -> list[str]:
    """Allowed types for approval edit: config ∩ connector (or connector only)."""
    connector = ctx.connector
    if connector is None:
        cfg_types = ctx.config.engagement.reactions.types
        return list(cfg_types) if cfg_types else []
    caps = connector.capabilities().reactions
    if caps is None:
        return []
    return resolve_allowed_types(ctx.config.engagement.reactions, caps.allowed_types)


def _allowed_vote_values(ctx: RunContext) -> list[int]:
    """Allowed vote values for approval edit: config ∩ connector."""
    connector = ctx.connector
    if connector is None:
        cfg_values = ctx.config.engagement.votes.values
        return list(cfg_values) if cfg_values else [-1, 0, 1]
    caps = connector.capabilities().votes
    if caps is None:
        return []
    return resolve_allowed_values(ctx.config.engagement.votes, caps.allowed_values)
