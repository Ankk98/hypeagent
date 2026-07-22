"""Targeting strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hypeagent.models.content import Content
from hypeagent.models.run import RunContext


class TargetingStrategy(ABC):
    """Filter and rank candidate content for an agent run."""

    name: str

    @abstractmethod
    def apply(
        self,
        contents: list[Content],
        ctx: RunContext,
        params: dict[str, Any],
    ) -> list[Content]:
        """Return candidate contents after applying this strategy."""
