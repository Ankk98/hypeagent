# Knowledge tool guide

Knowledge tools let agents fetch dynamic context during drafting. The LLM can request a tool by name; hypeagent runs it and feeds the result back (up to two rounds per action).

Run commands from your project directory with the venv activated (`source .venv/bin/activate`).

## Quick start

1. Create a module under `./tools/`:

```python
# tools/my_app/show_context.py

from __future__ import annotations

from typing import Any

from hypeagent.models.run import RunContext

DESCRIPTION = "Returns stable show metadata for a show_id argument."


def run(ctx: RunContext, arguments: dict[str, Any]) -> str:
    show_id = arguments.get("show_id", "default")
    return f"Show {show_id}: reality TV format, 12 contestants..."
```

2. Register it in `hypeagent.yaml`:

```yaml
knowledge:
  tools:
    - name: show_context
      module: tools.my_app.show_context
      description: Returns stable show metadata for a show_id argument.
```

3. Run `hypeagent validate` to confirm the module imports.

## Contract

Every tool module must expose:

| Symbol | Required | Description |
| --- | --- | --- |
| `run(ctx, arguments) -> str` | yes | Execute the tool; return plain text for the LLM |
| `DESCRIPTION` | no | Fallback description if config `description` is empty |

### Arguments

- `ctx` — `RunContext` with config, secrets, DB, logger, and current agent/persona
- `arguments` — `dict` parsed from the LLM's JSON tool request

### Limits

- Results are truncated to **2000 characters**
- Maximum **2 tool rounds** per drafted action
- Tool modules are imported from the **current working directory** (project root)

## How the LLM calls tools

During drafting, the LLM may output JSON like:

```json
{"tool": "show_context", "arguments": {"show_id": "s42"}}
```

hypeagent executes the tool, appends the result to the prompt, and re-calls the LLM. In dry-run mode, tool calls are logged but nothing is published.

## Built-in tools

These ship with hypeagent and can be referenced by module path:

| Tool | Module | Purpose |
| --- | --- | --- |
| `static_file` | `hypeagent.knowledge.builtins.static_file` | Read a file path from arguments |
| `short_term_memory` | `hypeagent.knowledge.builtins.short_term_memory` | Recent actions by persona from SQLite |

Example config:

```yaml
knowledge:
  tools:
    - name: memory
      module: hypeagent.knowledge.builtins.short_term_memory
      description: Recent comments and replies by this persona.
```

## Static knowledge vs tools

Use **static knowledge** for fixed briefs that don't change per action:

```yaml
knowledge:
  static:
    - inline: "This app is about reality TV predictions."
      max_chars: 500
    - path: ./briefs/show_bible.md
      max_chars: 800
```

Use **tools** when the agent needs to look something up based on the thread or LLM choice.

## Example tools

Working examples ship in:

- [examples/reddit/tools/my_app/](../examples/reddit/tools/my_app/) — `show_context` and `recent_episode`
- [tools/my_app/](../tools/my_app/) — same modules for development/testing

## Error handling

- Import failures surface during `hypeagent validate`
- Runtime exceptions are caught, logged, and returned to the LLM as an error string
- Unknown tool names raise at execution time

## Tips

- Keep `description` specific — the LLM uses it to decide when to call the tool
- Return concise, factual text; the 2000-char cap is enforced
- Use `ctx.db` and repositories for reading run history (see `short_term_memory` builtin)
- Never log secrets or return raw tokens from tools

## Further reading

- [Config reference](../docs/config_reference.md)
- [Implementation plan](../docs/implementation_plan.md) §7
