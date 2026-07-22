"""Prompt template assembly for the agent drafter."""

from __future__ import annotations

from hypeagent.config.schema import HypeagentConfig, PersonaConfig
from hypeagent.models.action import ActionType
from hypeagent.models.content import Comment, Thread


def _block(title: str, text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    return f"## {title}\n{text.strip()}"


def assemble_extra_info_blocks(
    config: HypeagentConfig,
    persona: PersonaConfig,
    *,
    knowledge_extra_infos: list[str] | None = None,
) -> str:
    """Build extra_info sections injected into the drafter system prompt (§4.2)."""
    blocks: list[str] = []
    for block in (
        _block("Global", config.extra_info),
        _block("Platform", config.platform.extra_info),
        _block("LLM style", config.llm.extra_info),
        _block("Run rules", config.run.extra_info),
        _block("Targeting", config.targeting.extra_info),
        _block("Persona extras", persona.extra_info),
    ):
        if block is not None:
            blocks.append(block)

    if knowledge_extra_infos:
        combined = "\n".join(info.strip() for info in knowledge_extra_infos if info.strip())
        knowledge_block = _block("Knowledge", combined)
        if knowledge_block is not None:
            blocks.append(knowledge_block)

    return "\n\n".join(blocks)


def format_thread_comments(comments: list[Comment]) -> str:
    """Format a flat comment list for the drafter user prompt."""
    if not comments:
        return "(no comments yet)"

    lines: list[str] = []
    for comment in comments:
        indent = "  " * comment.depth
        lines.append(
            f"{indent}@{comment.author_display}: {comment.body}"
        )
    return "\n".join(lines)


def build_drafter_system_prompt(
    config: HypeagentConfig,
    persona: PersonaConfig,
    *,
    action_type: ActionType,
    static_knowledge_summary: str = "",
    tool_results: str = "",
    knowledge_extra_infos: list[str] | None = None,
) -> str:
    """Assemble the drafter system prompt (§9.3)."""
    extra_info_blocks = assemble_extra_info_blocks(
        config,
        persona,
        knowledge_extra_infos=knowledge_extra_infos,
    )
    languages = ", ".join(persona.languages) if persona.languages else "unknown"
    city_line = f"City: {persona.city}" if persona.city else ""

    knowledge_parts: list[str] = []
    if static_knowledge_summary.strip():
        knowledge_parts.append(static_knowledge_summary.strip())
    if tool_results.strip():
        knowledge_parts.append(tool_results.strip())
    knowledge_section = "\n\n".join(knowledge_parts)

    sections = [
        "You write social media comments as a real human persona.",
        "Output ONLY the comment text. No quotes, no explanation.",
    ]
    if extra_info_blocks:
        sections.append(extra_info_blocks)
    sections.extend(
        [
            "## Persona",
            persona.brief.strip(),
            city_line,
            f"Languages: {languages}",
        ]
    )
    if knowledge_section:
        sections.extend(["## Knowledge", knowledge_section])
    sections.extend(
        [
            "## Rules",
            "- Match persona voice and language.",
            "- Keep it short unless thread is serious.",
            "- Do not break character.",
            f"- action_type: {action_type.value}",
        ]
    )
    return "\n\n".join(part for part in sections if part)


def build_drafter_user_prompt(
    thread: Thread,
    action_type: ActionType,
    *,
    parent: Comment | None = None,
) -> str:
    """Assemble the drafter user prompt (§9.3)."""
    content = thread.content
    lines = [
        "## Post",
        f"Author: {content.author_display}",
        f"Text: {content.body}",
        "",
        "## Comments",
        format_thread_comments(thread.comments),
    ]
    if action_type == ActionType.REPLY and parent is not None:
        lines.extend(
            [
                "",
                "## Reply target",
                f"Author: {parent.author_display}",
                f"Text: {parent.body}",
            ]
        )
    lines.extend(["", f"Write one {action_type.value}."])
    return "\n".join(lines)
