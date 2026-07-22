"""Built-in tool: read a file path and return truncated contents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hypeagent.knowledge.static import truncate_text
from hypeagent.models.run import RunContext

DESCRIPTION = "Read a file path and return its text contents."


def run(ctx: RunContext, arguments: dict[str, Any]) -> str:
    path_arg = arguments.get("path")
    if not isinstance(path_arg, str) or not path_arg.strip():
        return "Error: 'path' argument is required."

    max_chars = arguments.get("max_chars", 2000)
    if not isinstance(max_chars, int) or max_chars < 1:
        max_chars = 2000

    file_path = Path(path_arg)
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()

    if not file_path.is_file():
        return f"Error: file not found: {file_path}"

    text = file_path.read_text(encoding="utf-8")
    return truncate_text(text, max_chars)
