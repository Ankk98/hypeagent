"""Canonical platform content models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class Content:
    id: str
    kind: Literal["post"]
    author_id: str
    author_display: str
    body: str
    created_at: datetime
    comment_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Comment:
    id: str
    content_id: str
    parent_id: str | None
    author_id: str
    author_display: str
    body: str
    created_at: datetime
    depth: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Thread:
    content: Content
    comments: list[Comment]
