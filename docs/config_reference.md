# Config reference

hypeagent reads two YAML files from your project directory:

| File | Committed | Purpose |
| --- | --- | --- |
| `hypeagent.yaml` | Yes | Agents, personas, platform, budgets, targeting |
| `secrets.local.yaml` | No (gitignored) | LLM API key and per-account tokens |

Install hypeagent in a project venv before running commands:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install hypeagent
```

Validate both config files with `hypeagent validate`.

## Global options

These CLI flags apply to every command:

| Flag | Default | Description |
| --- | --- | --- |
| `--config`, `-c` | `hypeagent.yaml` | Path to config file |
| `--secrets`, `-s` | `secrets.local.yaml` | Path to secrets file |
| `--db` | `~/.hypeagent/hypeagent.db` | SQLite database path |
| `--verbose`, `-v` | off | Enable debug logging |

## `hypeagent.yaml`

Unknown keys are rejected. All `extra_info` fields are injected into LLM prompts.

### Top level

| Key | Required | Description |
| --- | --- | --- |
| `version` | yes | Must be `1` |
| `name` | yes | Run name (stored in SQLite) |
| `extra_info` | no | Global hints for all agents (`## Global` in prompts) |

### `platform`

| Key | Required | Description |
| --- | --- | --- |
| `connector` | yes | Built-in name (`reddit`) or path (`./platforms/my_app.py`) |
| `base_url` | yes | Platform API base URL |
| `user_agent` | yes | HTTP User-Agent for all platform requests |
| `subreddit` | Reddit only | Target subreddit name |
| `extra_info` | no | Platform context for prompts |

### `http`

| Key | Default | Description |
| --- | --- | --- |
| `timeout_seconds` | `30` | Per-request timeout |
| `retry_count` | `2` | Retries on 5xx and transport errors |

### `llm`

| Key | Default | Description |
| --- | --- | --- |
| `provider` | `openrouter` | `openrouter` or `openai_compatible` |
| `base_url` | — | API base URL (e.g. `https://openrouter.ai/api/v1`) |
| `model` | — | Model identifier (e.g. `openai/gpt-4o-mini`) |
| `temperature` | `0.9` | Sampling temperature |
| `max_tokens` | `256` | Max completion tokens per call |
| `extra_info` | no | Style hints for the drafter |

### `budgets`

| Key | Default | Description |
| --- | --- | --- |
| `llm_daily_usd` | — | Max LLM spend per calendar day (UTC) |
| `llm_total_usd` | — | Max lifetime LLM spend (must be ≥ daily) |
| `max_actions_per_run` | `50` | Cap on published + dry-run actions per invocation |

### `run`

| Key | Required | Description |
| --- | --- | --- |
| `agents` | yes | Ordered list of persona IDs to run sequentially |
| `per_agent.comments` | yes | Top-level comments per agent per run |
| `per_agent.replies` | yes | Thread replies per agent per run |
| `reply_depth_max` | `2` | Max comment nesting depth for replies |
| `extra_info` | no | Run-level rules for prompts |

### `targeting`

| Key | Required | Description |
| --- | --- | --- |
| `strategy` | yes | See [targeting strategies](#targeting-strategies) |
| `params` | no | Strategy-specific parameters |
| `extra_info` | no | Targeting hints for prompts |

#### Targeting strategies

| Strategy | Params | Behavior |
| --- | --- | --- |
| `random_with_comments_last_24h` | `since_hours` (24), `min_comment_count` (1) | Random pick from recent posts with comments |
| `recent` | — | Newest post with at least one comment |
| `oldest_unanswered` | — | Post with fewest comments from agent accounts |
| `allowlist` | `content_ids: [id1, id2]` | Only listed content IDs, in order |

### `personas.<id>`

| Key | Required | Description |
| --- | --- | --- |
| `account` | yes | Key in `secrets.accounts` |
| `brief` | yes | Persona description for the drafter |
| `city` | no | Location hint |
| `languages` | no | Language/style hints |
| `extra_info` | no | Additional persona context |

Every ID in `run.agents` must exist in `personas`.

### `knowledge`

#### `knowledge.static[]`

Each item must have exactly one of `inline` or `path`.

| Key | Default | Description |
| --- | --- | --- |
| `inline` | — | Inline text brief |
| `path` | — | Path to a markdown/text file (relative to config dir) |
| `max_chars` | `500` | Truncation limit |
| `extra_info` | no | Context label for this brief |

#### `knowledge.tools[]`

| Key | Required | Description |
| --- | --- | --- |
| `name` | yes | Tool name used in LLM JSON requests |
| `module` | yes | Python module path (e.g. `tools.my_app.show_context`) |
| `description` | yes | What the tool returns (shown to the LLM) |

See [tool guide](../tools/README.md).

### `logging`

| Key | Default | Description |
| --- | --- | --- |
| `level` | `info` | `debug`, `info`, `warning`, or `error` |
| `file` | `~/.hypeagent/logs/hypeagent.log` | Log file path (relative paths resolve from config dir) |
| `console` | `true` | Mirror logs to stderr |

## `secrets.local.yaml`

| Key | Required | Description |
| --- | --- | --- |
| `llm.api_key` | yes | OpenRouter or compatible API key |
| `accounts.<id>.user_id` | yes | Platform user ID for the account |
| `accounts.<id>.token` | yes | Bearer or refresh token |
| `accounts.<id>.extra` | no | Connector-specific fields (e.g. Reddit `client_id`) |

Each `personas.<id>.account` must reference a key in `accounts`.

### Reddit account extras

```yaml
accounts:
  my_bot:
    user_id: "t2_abc123"
    token: "<refresh_token>"
    extra:
      client_id: YOUR_CLIENT_ID
      client_secret: YOUR_CLIENT_SECRET
```

## Example

See [examples/reddit/hypeagent.yaml](../examples/reddit/hypeagent.yaml) for a complete working config.
