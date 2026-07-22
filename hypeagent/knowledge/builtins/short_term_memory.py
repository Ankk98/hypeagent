"""Built-in tool: return recent actions by the current persona from SQLite."""

from __future__ import annotations

from typing import Any

from hypeagent.db.repositories.agent_memory import AgentMemoryRepository
from hypeagent.models.run import RunContext

DESCRIPTION = "Return recent actions by this persona from short-term memory."


def run(ctx: RunContext, arguments: dict[str, Any]) -> str:
    limit = arguments.get("limit", 10)
    if not isinstance(limit, int) or limit < 1:
        limit = 10

    repo = AgentMemoryRepository(ctx.db)
    entries = repo.get_recent(ctx.agent_id, limit=limit)
    if not entries:
        return "No recent actions recorded for this persona."

    lines = ["Recent actions:"]
    for entry in entries:
        lines.append(
            f"- [{entry.created_at}] {entry.action_type} on {entry.content_id}: "
            f"{entry.text_preview}"
        )
    return "\n".join(lines)
