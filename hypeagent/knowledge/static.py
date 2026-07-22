"""Static knowledge loader: inline text and file briefs with truncation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hypeagent.config.schema import HypeagentConfig, StaticKnowledgeItem


@dataclass(frozen=True)
class StaticKnowledgeSummary:
    """Combined static knowledge for prompt injection."""

    summary: str
    extra_infos: list[str]


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending ellipsis when shortened."""
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    if max_chars <= 3:
        return stripped[:max_chars]
    return stripped[: max_chars - 3].rstrip() + "..."


def _load_item_text(item: StaticKnowledgeItem, base_dir: Path) -> str:
    if item.inline is not None:
        return item.inline
    assert item.path is not None
    file_path = Path(item.path)
    if not file_path.is_absolute():
        file_path = (base_dir / file_path).resolve()
    if not file_path.is_file():
        msg = f"Static knowledge file not found: {file_path}"
        raise FileNotFoundError(msg)
    return file_path.read_text(encoding="utf-8")


class StaticKnowledgeLoader:
    """Load and summarize static knowledge from config."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir is not None else Path.cwd()

    def load_item(self, item: StaticKnowledgeItem) -> str:
        """Load a single static knowledge item with max_chars truncation."""
        text = _load_item_text(item, self._base_dir)
        return truncate_text(text, item.max_chars)

    def summarize(self, config: HypeagentConfig) -> StaticKnowledgeSummary:
        """Load all static knowledge entries and collect extra_info values."""
        parts: list[str] = []
        extra_infos: list[str] = []
        for item in config.knowledge.static:
            parts.append(self.load_item(item))
            if item.extra_info and item.extra_info.strip():
                extra_infos.append(item.extra_info.strip())
        summary = "\n\n".join(part for part in parts if part)
        return StaticKnowledgeSummary(summary=summary, extra_infos=extra_infos)
