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
| `per_agent.comments` | no (default `0`) | Top-level comments per agent per run |
| `per_agent.replies` | no (default `1`) | Thread replies per agent per run |
| `per_agent.reactions` | no (default `0`) | Reaction publishes per agent per run |
| `per_agent.votes` | no (default `0`) | Scalar vote publishes per agent per run |
| `action_priority` | no | Kind order when multiple quotas remain: `reply`, `comment`, `reaction`, `vote` (default: that order) |
| `reply_depth_max` | `2` | Max comment nesting depth for replies |
| `extra_info` | no | Run-level rules for prompts |

### `engagement`

Optional. Controls non-text engagement. Reddit configs can omit this section.

#### `engagement.reactions`

| Key | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Prefer explicit enable; also implied when `per_agent.reactions > 0` for validation |
| `targets` | `[content]` | Where to react: `content`, `comment`, or both |
| `types` | all connector-allowed | Subset of connector reaction vocabulary |
| `strategy` | `weighted` | `weighted`, `random`, `llm_choose`, or `persona_affinity` |
| `weights` | equal | Relative weights when `strategy=weighted` (keys must be allowed types) |
| `skip_if_already_reacted` | `true` | Skip targets where `current_engagement` reports `myReaction` |
| `avoid_content_author_ids` | `[]` | Do not react to content/comments by these author IDs |

`hypeagent validate` fails if reactions are requested (`per_agent.reactions > 0` or `enabled: true`) but the connector does not advertise `capabilities().reactions`, or if `types` / `targets` are outside the connector allowlist.

Example:

```yaml
run:
  per_agent:
    comments: 0
    replies: 0
    reactions: 1
  action_priority: [reaction, comment, reply]

engagement:
  reactions:
    enabled: true
    targets: [content]
    types: [agree, insightful, like]
    strategy: weighted
    weights:
      agree: 0.4
      insightful: 0.3
      like: 0.3
    skip_if_already_reacted: true
```

#### `engagement.votes`

| Key | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Prefer explicit enable; also implied when `per_agent.votes > 0` for validation |
| `targets` | `[content]` | Where to vote: `content`, `comment`, or both |
| `values` | all connector-allowed | Subset of connector vote values (typically `-1`, `0`, `1`) |
| `skip_if_already_voted` | `true` | Skip targets where `current_engagement` reports `myVote` |
| `avoid_content_author_ids` | `[]` | Do not vote on content/comments by these author IDs |

`hypeagent validate` fails if votes are requested (`per_agent.votes > 0` or `enabled: true`) but the connector does not advertise `capabilities().votes`, or if `values` / `targets` are outside the connector allowlist.

Reddit example (upvote posts only):

```yaml
run:
  per_agent:
    comments: 0
    replies: 0
    reactions: 0
    votes: 1
  action_priority: [vote, reply, comment]

engagement:
  votes:
    enabled: true
    targets: [content]
    values: [1]
    skip_if_already_voted: true
```

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
