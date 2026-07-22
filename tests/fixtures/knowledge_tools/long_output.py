"""Fixture tool that returns long output for truncation tests."""

from __future__ import annotations

from typing import Any

DESCRIPTION = "Returns a long string."


def run(_ctx: object, _arguments: dict[str, Any]) -> str:
    return "x" * 5000
