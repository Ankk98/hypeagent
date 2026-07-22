"""Example knowledge tool: most recent episode summary."""

from __future__ import annotations

from typing import Any

from hypeagent.models.run import RunContext

DESCRIPTION = "Returns summary of the most recent aired episode."


def run(ctx: RunContext, arguments: dict[str, Any]) -> str:
    show_id = arguments.get("show_id", "default")
    return (
        f"Show {show_id} — latest episode: two contestants eliminated, "
        "twist vote opened for fan predictions."
    )
