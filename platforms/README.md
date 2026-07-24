# Platform connector guide

hypeagent talks to social platforms through **connectors** — Python classes that map platform APIs to canonical `Content`, `Comment`, and `Thread` models.

Run commands from your project directory with the venv activated (`source .venv/bin/activate`).

## Quick start

1. Create `./platforms/my_app.py` in your project directory.
2. Reference it in `hypeagent.yaml`:

```yaml
platform:
  connector: ./platforms/my_app.py
  base_url: https://api.myapp.com/v1
  user_agent: hypeagent/0.1 (my-app-bot)
```

3. Run `hypeagent validate` to confirm the connector loads.

Built-in Reddit connector:

```yaml
platform:
  connector: reddit
  base_url: https://oauth.reddit.com
  user_agent: hypeagent/0.1 (by u/yourname)
  subreddit: test
```

## Contract

Subclass `PlatformConnector` from `hypeagent.platforms.base` and implement three methods:

| Method | Returns | Purpose |
| --- | --- | --- |
| `list_contents(ctx, *, since)` | `list[Content]` | Candidate posts since a datetime |
| `get_thread(ctx, content_id)` | `Thread` | Post plus flat comment list |
| `publish_comment(ctx, content_id, text, parent_comment_id)` | `Comment` | Post a comment or reply |

Optional overrides:

| Method | Default behavior |
| --- | --- |
| `capabilities()` | Comments + replies only (`PlatformCapabilities()`); no reactions/votes |
| `execute(ctx, spec)` | Routes `COMMENT`/`REPLY` to `publish_comment` and `REACT` to `publish_reaction` |
| `publish_reaction(ctx, target, reaction_type)` | Raises unless overridden; used when `capabilities().reactions` is set |
| `current_engagement(ctx, target)` | Returns `{}`. For reactions, return `{"myReaction": "<type>"}` when the account already reacted so the planner can honor `skip_if_already_reacted` |
| `can_reply(ctx, thread, parent, reply_depth_max)` | Checks comment depth against `reply_depth_max` |
| `filter_candidates(ctx, contents, strategy)` | Delegates to the targeting registry |

Raise `PlatformError` on API failures.

The agent loop publishes via `connector.execute(ctx, ActionSpec)`. Keep implementing `publish_comment` for text actions; override `publish_reaction` (and `capabilities`) when adding reactions.

### Reactions contract

To support `run.per_agent.reactions` / `engagement.reactions`:

1. Override `capabilities()` and return a non-null `ReactionCapability` with `target_kinds`, `allowed_types`, and `mode` (`toggle` / `set` / `additive`).
2. Override `publish_reaction()` (or `execute()`) to handle `ActionKind.REACT` (payload `reaction_type`, target `CONTENT` or `COMMENT`).
3. Optionally override `current_engagement()` so repeated toggles do not clear an existing reaction.

Prefer caching `myReaction` while listing posts / loading threads so the planner does not need one HTTP call per comment candidate.

`hypeagent validate` checks that configured reaction types and targets are subsets of what the connector advertises.

See the runnable [custom typed-reactions example](../examples/custom-reactions/)
for a complete file-based connector, YAML config, bearer-token HTTP mapping, and
the expected post/comment response shapes.

See [engagement actions plan](../docs/engagement_actions_plan.md) for the full capability model.

### Canonical models

```python
@dataclass(frozen=True)
class Content:
    id: str
    kind: Literal["post"]          # v1: posts only
    author_id: str
    author_display: str
    body: str
    created_at: datetime
    comment_count: int
    metadata: dict[str, Any]       # e.g. agent_comment_count for oldest_unanswered

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
    comments: list[Comment]        # flat list with parent_id links
```

### Constructor

```python
def __init__(
    self,
    platform_config: PlatformConfig,
    account: AccountSecret,
    http: HttpConfig,
) -> None:
    ...
```

The core instantiates one connector per agent run, bound to that agent's account from `secrets.local.yaml`.

## File-based connectors

When `connector` is a `.py` path, hypeagent loads the module and looks for:

1. `{StemCamelCase}Connector` (e.g. `my_app.py` → `MyAppConnector`)
2. Any other `PlatformConnector` subclass in the file

## Example skeleton

```python
"""MyApp platform connector."""

from __future__ import annotations

from datetime import datetime

from hypeagent.config.schema import HttpConfig, PlatformConfig
from hypeagent.config.secrets_schema import AccountSecret
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext
from hypeagent.platforms.base import PlatformConnector, PlatformError
from hypeagent.platforms.http_client import HttpClient


class MyAppConnector(PlatformConnector):
    name = "my_app"

    def __init__(
        self,
        platform_config: PlatformConfig,
        account: AccountSecret,
        http: HttpConfig,
    ) -> None:
        super().__init__(platform_config, account, http)
        self._http = HttpClient(http, platform_config.user_agent)

    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        # Fetch posts from your API, map to Content objects
        ...

    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        # Fetch post + comments, return Thread
        ...

    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        # POST comment/reply; raise PlatformError on failure
        ...
```

## Reddit reference

See `hypeagent/platforms/reddit.py` for the shipped reference implementation. It uses:

- OAuth refresh tokens from `secrets.accounts.<id>.token`
- `client_id` and `client_secret` in `secrets.accounts.<id>.extra`
- `GET /r/{subreddit}/new` for listing
- `GET /comments/{id}` for threads
- `POST /api/comment` for publishing

Install Reddit support inside your project venv (optional; the connector uses `httpx` directly):

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install hypeagent[reddit]
```

## Tips

- Set `metadata["agent_comment_count"]` on `Content` if you use the `oldest_unanswered` targeting strategy.
- Use `ctx.logger` for structured debug output — never log tokens.
- Reuse `HttpClient` from `hypeagent.platforms.http_client` for retries, timeouts, and User-Agent headers.

## Further reading

- [Config reference](../docs/config_reference.md)
- [Implementation plan](../docs/implementation_plan.md) §6
