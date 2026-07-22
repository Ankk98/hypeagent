"""Knowledge tool registry, dynamic import, and LLM tool-round execution."""

from __future__ import annotations

import importlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hypeagent.config.schema import ToolConfig
from hypeagent.llm.client import LLMClient
from hypeagent.models.action import ToolCallRecord
from hypeagent.models.run import RunContext

MAX_TOOL_RESULT_CHARS = 2000
MAX_TOOL_ROUNDS = 2

BUILTIN_TOOLS: dict[str, str] = {
    "static_file": "hypeagent.knowledge.builtins.static_file",
    "short_term_memory": "hypeagent.knowledge.builtins.short_term_memory",
}

ToolRunFn = Callable[[RunContext, dict[str, Any]], str]


class ToolLoadError(Exception):
    """Raised when a knowledge tool module cannot be imported or is invalid."""


@dataclass(frozen=True)
class LoadedTool:
    name: str
    description: str
    run: ToolRunFn


def _ensure_tools_path_on_sys_path(module_path: str) -> None:
    """Add cwd to sys.path so `tools.my_app.foo` imports resolve from project root."""
    if module_path.startswith("tools."):
        cwd = str(Path.cwd().resolve())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)


def load_tool_module(module_path: str) -> Any:
    """Import a tool module by dotted path, ensuring user tools/ is on sys.path."""
    _ensure_tools_path_on_sys_path(module_path)
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        msg = f"Cannot import tool module {module_path!r}: {exc}"
        raise ToolLoadError(msg) from exc


def _resolve_run_fn(module: Any, module_path: str) -> ToolRunFn:
    run_fn = getattr(module, "run", None)
    if run_fn is None or not callable(run_fn):
        msg = f"Tool module {module_path!r} must expose run(ctx, arguments) -> str"
        raise ToolLoadError(msg)
    return run_fn  # type: ignore[no-any-return]


def load_tool(tool_config: ToolConfig) -> LoadedTool:
    """Load a configured knowledge tool."""
    module = load_tool_module(tool_config.module)
    run_fn = _resolve_run_fn(module, tool_config.module)
    description = tool_config.description
    module_description = getattr(module, "DESCRIPTION", None)
    if not description.strip() and isinstance(module_description, str):
        description = module_description
    return LoadedTool(
        name=tool_config.name,
        description=description,
        run=run_fn,
    )


def validate_tools(tools: list[ToolConfig]) -> list[str]:
    """Validate tool imports; return a list of error messages (empty if all ok)."""
    errors: list[str] = []
    for tool_config in tools:
        try:
            load_tool(tool_config)
        except ToolLoadError as exc:
            errors.append(f"tool {tool_config.name!r} ({tool_config.module}): {exc}")
    return errors


def truncate_tool_result(text: str) -> str:
    """Enforce max chars on tool output (§7.1)."""
    return text[:MAX_TOOL_RESULT_CHARS]


def _extract_json_objects(text: str) -> list[str]:
    """Extract top-level JSON object substrings, handling nested braces."""
    objects: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "{":
            index += 1
            continue
        depth = 0
        start = index
        for offset, char in enumerate(text[index:], start=index):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[start : offset + 1])
                    index = offset + 1
                    break
        else:
            break
    return objects


def parse_tool_request(text: str) -> tuple[str, dict[str, Any]] | None:
    """
    Parse an LLM response for a JSON tool request.

    Accepts a full JSON body or a JSON object embedded in surrounding text.
    """
    stripped = text.strip()
    if not stripped:
        return None

    candidates = [stripped]
    if not stripped.startswith("{"):
        candidates.extend(_extract_json_objects(stripped))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        tool_name = payload.get("tool")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        return tool_name.strip(), arguments

    return None


class ToolRegistry:
    """Registry of knowledge tools from config."""

    def __init__(self, tools: list[ToolConfig] | None = None) -> None:
        self._tools: dict[str, LoadedTool] = {}
        for tool_config in tools or []:
            loaded = load_tool(tool_config)
            self._tools[loaded.name] = loaded

    def get(self, name: str) -> LoadedTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def descriptions_block(self) -> str:
        """Format tool descriptions for the drafter system prompt."""
        if not self._tools:
            return ""
        lines = ["Available tools (request via JSON: {\"tool\": \"name\", \"arguments\": {}}):"]
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def execute(self, ctx: RunContext, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool by name and enforce result size limits."""
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(sorted(self._tools)) or "(none)"
            msg = f"Unknown tool {name!r}; configured tools: {known}"
            raise ToolLoadError(msg)

        started = time.perf_counter()
        result = truncate_tool_result(str(tool.run(ctx, arguments)))
        duration_ms = int((time.perf_counter() - started) * 1000)
        ctx.logger.debug(
            "event=tool_call tool=%s duration_ms=%d result_chars=%d",
            name,
            duration_ms,
            len(result),
        )
        return result


@dataclass
class ToolRoundResult:
    """Result of LLM completion with optional tool rounds."""

    final_text: str
    tool_calls: list[ToolCallRecord]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str


class ToolExecutor:
    """Execute up to MAX_TOOL_ROUNDS tool calls during a single draft."""

    def __init__(self, registry: ToolRegistry, llm_client: LLMClient) -> None:
        self._registry = registry
        self._llm_client = llm_client

    def complete_with_tools(
        self,
        ctx: RunContext,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolRoundResult:
        """
        Call the LLM, optionally executing tool requests for up to MAX_TOOL_ROUNDS.

        When the model returns a JSON tool request, the tool runs, the result is
        appended to the conversation, and the LLM is called again.
        """
        tool_calls: list[ToolCallRecord] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        resolved_model = model or ctx.config.llm.model

        system_prompt = system
        tools_block = self._registry.descriptions_block()
        if tools_block:
            system_prompt = f"{system}\n\n{tools_block}"

        conversation = list(messages)
        response = self._llm_client.complete(
            system=system_prompt,
            messages=conversation,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            run_id=ctx.run_id,
            agent_id=ctx.agent_id,
        )
        total_tokens_in += response.tokens_in
        total_tokens_out += response.tokens_out
        total_cost += response.cost_usd
        resolved_model = response.model
        content = response.content
        ctx.logger.debug(
            (
                "run_id=%s agent=%s event=llm_call model=%s "
                "tokens_in=%d tokens_out=%d cost_usd=%.4f"
            ),
            ctx.run_id,
            ctx.agent_id,
            response.model,
            response.tokens_in,
            response.tokens_out,
            response.cost_usd,
        )

        for _round in range(MAX_TOOL_ROUNDS):
            request = parse_tool_request(content)
            if request is None:
                break

            tool_name, arguments = request
            started = time.perf_counter()
            try:
                result = self._registry.execute(ctx, tool_name, arguments)
            except ToolLoadError as exc:
                result = f"Tool error: {exc}"
            duration_ms = int((time.perf_counter() - started) * 1000)

            tool_calls.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    result_preview=result[:200],
                    duration_ms=duration_ms,
                )
            )

            conversation.append({"role": "assistant", "content": content})
            conversation.append(
                {
                    "role": "user",
                    "content": f"Tool {tool_name} result:\n{result}\n\nWrite one comment.",
                }
            )

            response = self._llm_client.complete(
                system=system_prompt,
                messages=conversation,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
            )
            total_tokens_in += response.tokens_in
            total_tokens_out += response.tokens_out
            total_cost += response.cost_usd
            resolved_model = response.model
            content = response.content
            ctx.logger.debug(
                (
                    "run_id=%s agent=%s event=llm_call model=%s "
                    "tokens_in=%d tokens_out=%d cost_usd=%.4f"
                ),
                ctx.run_id,
                ctx.agent_id,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            )

        return ToolRoundResult(
            final_text=content.strip(),
            tool_calls=tool_calls,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost,
            model=resolved_model,
        )
