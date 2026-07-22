"""LLM draft generation with static knowledge and tool rounds."""

from __future__ import annotations

from hypeagent.knowledge.static import StaticKnowledgeLoader
from hypeagent.knowledge.tools import ToolExecutor, ToolRoundResult
from hypeagent.llm.prompts import build_drafter_system_prompt, build_drafter_user_prompt
from hypeagent.models.action import ActionType
from hypeagent.models.content import Comment, Thread
from hypeagent.models.run import RunContext


class Drafter:
    """Generate comment/reply draft text via the LLM (§10)."""

    def __init__(
        self,
        static_loader: StaticKnowledgeLoader,
        tool_executor: ToolExecutor,
    ) -> None:
        self._static_loader = static_loader
        self._tool_executor = tool_executor

    def draft(
        self,
        ctx: RunContext,
        thread: Thread,
        action_type: ActionType,
        parent: Comment | None,
    ) -> ToolRoundResult:
        """Draft comment text, optionally invoking knowledge tools."""
        static = self._static_loader.summarize(ctx.config)
        system = build_drafter_system_prompt(
            ctx.config,
            ctx.persona,
            action_type=action_type,
            static_knowledge_summary=static.summary,
            knowledge_extra_infos=static.extra_infos,
        )
        user = build_drafter_user_prompt(thread, action_type, parent=parent)
        return self._tool_executor.complete_with_tools(
            ctx,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
