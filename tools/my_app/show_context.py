"""Example knowledge tool: stable show metadata."""

from __future__ import annotations

from typing import Any

from hypeagent.models.run import RunContext

DESCRIPTION = "Returns stable show metadata for a show_id argument."


def run(ctx: RunContext, arguments: dict[str, Any]) -> str:
    show_id = arguments.get("show_id", "default")
    return (
        f"Show {show_id}: reality TV format, 12 contestants, "
        "weekly eliminations, fan predictions leaderboard."
    )
