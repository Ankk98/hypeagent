"""Interactive approval prompts before publishing (§10.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from hypeagent.models.action import ActionType, ProposedAction
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
        while True:
            self._render(ctx, proposed, draft_text)
            choice = self._read_choice()
            if choice == ApprovalDecision.PUBLISH:
                return ApprovalResponse(ApprovalDecision.PUBLISH, draft_text)
            if choice == ApprovalDecision.SKIP:
                return ApprovalResponse(ApprovalDecision.SKIP, draft_text)
            if choice == ApprovalDecision.QUIT:
                return ApprovalResponse(ApprovalDecision.QUIT, draft_text)
            draft_text = self._edit_draft(draft_text)

    def _render(self, ctx: RunContext, proposed: ProposedAction, draft_text: str) -> None:
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
        if proposed.action_type == ActionType.REPLY and proposed.parent_comment_preview:
            lines.extend(
                [
                    "",
                    "Replying to:",
                    f'  "{proposed.parent_comment_preview}"',
                ]
            )
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
