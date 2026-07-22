# hypeagent — Implementation Plan

**Version:** 1.0  
**License:** MIT  
**Language:** Python 3.11+  
**Package name:** `hypeagent`  
**CLI entry point:** `hypeagent`  
**Status:** Authoritative build specification — all decisions below are final for v1 unless marked v2/v3.

---

## 1. Product definition

**hypeagent** is a standalone, open-source CLI that runs LLM-powered persona agents against any social platform. Founders configure behavior in YAML, wire platform I/O in a thin Python connector, and run dry-runs or live engagement to seed activity on their app.

### Locked decisions

| Topic | Decision |
| --- | --- |
| Distribution | Standalone CLI (`pip install hypeagent`), not an embeddable library |
| Config | `hypeagent.yaml` (committable) + `secrets.local.yaml` (gitignored) |
| Platform I/O | Python connector per platform; canonical internal model |
| Auth v1 | Per-user API tokens in secrets file; manual JWT rotation |
| LLM | OpenRouter default; any OpenAI-compatible API via config |
| Storage | SQLite at `~/.hypeagent/hypeagent.db` (override with `--db`) |
| Agent model | Sequential, independent agents; each sees fresh platform state |
| v1 actions | `comment`, `reply` on `post` content only |
| v1 default mode | `dry-run` |
| Publish modes | `dry-run` \| `approve` \| `auto` |
| Scheduling | `hypeagent cron-print` outputs crontab line; no in-process scheduler |
| Scale target | 50 personas/accounts per config |
| UI | None |
| SaaS | None |
| Browser automation | None |
| Reference platform | Reddit (shipped); private apps copy connector pattern |
| `extra_info` | On every major config node; always passed to prompts |
| Logs | File + stderr; structured fields; `--verbose` for debug |
| Usage CLI | `hypeagent usage print` and `hypeagent usage reset` |

---

## 2. Repository layout

```text
hypeagent/
├── pyproject.toml
├── README.md
├── LICENSE                          # MIT
├── hypeagent/
│   ├── __init__.py                  # __version__
│   ├── __main__.py                  # python -m hypeagent
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                  # Click/Typer root
│   │   ├── run.py
│   │   ├── dry_run.py
│   │   ├── validate.py
│   │   ├── usage.py
│   │   └── cron_print.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py                # YAML → hypeagentConfig
│   │   ├── secrets.py               # secrets.local.yaml → Secrets
│   │   └── schema.py                # Pydantic models
│   ├── models/
│   │   ├── __init__.py
│   │   ├── content.py               # Content, Comment, Thread
│   │   ├── action.py                # ProposedAction, PublishedAction
│   │   └── run.py                   # RunContext, RunMode, RunResult
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── migrations.py            # SQLite schema v1
│   │   └── repositories/
│   │       ├── usage.py
│   │       ├── runs.py
│   │       └── agent_memory.py      # v2
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py                # OpenAI-compatible client
│   │   ├── budget.py                # daily/total caps
│   │   └── prompts.py               # template assembly
│   ├── platforms/
│   │   ├── __init__.py
│   │   ├── base.py                  # PlatformConnector ABC
│   │   ├── registry.py              # load by name / path
│   │   ├── http_client.py           # shared requests wrapper
│   │   └── reddit.py                # reference connector
│   ├── targeting/
│   │   ├── __init__.py
│   │   ├── base.py                  # TargetingStrategy ABC
│   │   ├── registry.py
│   │   └── strategies/
│   │       ├── random_with_comments.py
│   │       ├── recent.py
│   │       ├── oldest_unanswered.py
│   │       └── allowlist.py
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── static.py                # file + inline brief loader
│   │   ├── tools.py                 # tool registry + executor
│   │   └── builtins/
│   │       ├── static_file.py
│   │       └── short_term_memory.py # sqlite-backed per persona
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py                  # AgentRunner
│   │   ├── planner.py               # decide comment vs reply
│   │   ├── drafter.py               # LLM draft text
│   │   └── approval.py              # CLI prompts
│   ├── logging/
│   │   ├── __init__.py
│   │   └── setup.py
│   └── hooks/
│       ├── __init__.py
│       └── registry.py              # v2: user Python hooks
├── examples/
│   ├── reddit/
│   │   ├── hypeagent.yaml
│   │   ├── secrets.example.yaml
│   │   └── briefs/show_bible.md
│   └── resume_maker/                # private doc only; not in public repo
│       └── README.md
├── platforms/                       # user-extensible drop-in (documented)
│   └── README.md
├── tools/                           # user-extensible drop-in (documented)
│   └── README.md
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

User project layout (founder-owned):

```text
my-startup/
├── hypeagent.yaml
├── secrets.local.yaml               # gitignored
├── platforms/
│   └── my_app.py                    # optional custom connector path
├── tools/
│   └── my_app/
│       ├── show_context.py
│       └── recent_episode.py
├── briefs/
│   └── show_bible.md
└── logs/                            # optional; default ~/.hypeagent/logs/
```

---

## 3. Canonical entities (Python)

All platform connectors map foreign data into these types. The agent loop never imports platform-specific types.

### 3.1 `Content`

```python
@dataclass(frozen=True)
class Content:
    id: str
    kind: Literal["post"]              # v1: post only; v2 adds take, thread, etc.
    author_id: str
    author_display: str
    body: str
    created_at: datetime
    comment_count: int
    metadata: dict[str, Any]           # platform extras; never required by core
```

### 3.2 `Comment`

```python
@dataclass(frozen=True)
class Comment:
    id: str
    content_id: str
    parent_id: str | None
    author_id: str
    author_display: str
    body: str
    created_at: datetime
    depth: int                         # 0 = top-level; computed by connector
    metadata: dict[str, Any]
```

### 3.3 `Thread`

```python
@dataclass(frozen=True)
class Thread:
    content: Content
    comments: list[Comment]            # flat list; parent_id links tree
```

### 3.4 `ActionType` (v1)

```python
class ActionType(str, Enum):
    COMMENT = "comment"                # top-level on content
    REPLY = "reply"                    # parent_comment_id set
```

### 3.5 `ProposedAction`

```python
@dataclass
class ProposedAction:
    run_id: str
    agent_id: str                      # persona key from config
    account_id: str                    # secrets.accounts key
    action_type: ActionType
    content_id: str
    content_body_preview: str          # first 200 chars for approval UI
    parent_comment_id: str | None
    parent_comment_preview: str | None # for approval UI
    draft_text: str
    targeting_strategy: str
    llm_model: str
    llm_tokens_in: int
    llm_tokens_out: int
    llm_cost_usd: float
    tool_calls: list[ToolCallRecord]
    created_at: datetime
```

### 3.6 `PublishedAction`

```python
@dataclass
class PublishedAction:
    proposed: ProposedAction
    platform_comment_id: str
    published_at: datetime
    approved_by: Literal["auto", "human", "dry-run"]
```

### 3.7 `RunContext`

```python
@dataclass
class RunContext:
    run_id: str
    mode: RunMode                      # dry_run | approve | auto
    config: hypeagentConfig
    secrets: Secrets
    agent_id: str
    persona: PersonaConfig
    account: AccountSecret
    connector: PlatformConnector
    db: Database
    logger: logging.Logger
    llm_client: LLMClient
    budget_guard: BudgetGuard
```

### 3.8 `RunMode`

```python
class RunMode(str, Enum):
    DRY_RUN = "dry_run"
    APPROVE = "approve"
    AUTO = "auto"
```

---

## 4. Config schema (`hypeagent.yaml`)

Validated with Pydantic v2 on load. Unknown keys are rejected.

```yaml
# hypeagent.yaml — full v1 schema
version: 1

name: my-seed-run
extra_info: >
  Optional global hints for all agents.

platform:
  connector: reddit                   # built-in name OR path: ./platforms/my_app.py
  base_url: https://oauth.reddit.com # connector-specific
  user_agent: hypeagent/1.0 (by u/yourname)
  extra_info: >
    Subreddit-focused. Respect rate limits.

http:
  timeout_seconds: 30
  retry_count: 2

llm:
  provider: openrouter                # openrouter | openai_compatible
  base_url: https://openrouter.ai/api/v1
  model: openai/gpt-4o-mini           # default model
  temperature: 0.9
  max_tokens: 256
  extra_info: >
    Prefer short casual replies.

budgets:
  llm_daily_usd: 2.00
  llm_total_usd: 50.00
  max_actions_per_run: 50             # cap across all agents in one invocation

run:
  agents:                             # ordered list; run sequentially
    - priya_blr
    - rohan_del
  per_agent:
    comments: 0
    replies: 1
  reply_depth_max: 2
  extra_info: >
    One reply per agent per run.

targeting:
  strategy: random_with_comments_last_24h
  params:
    since_hours: 24
    min_comment_count: 1
  extra_info: >
    Pick posts that already have discussion.

personas:
  priya_blr:
    account: priya_blr
    city: Bangalore
    languages: [hinglish, en]
    brief: >
      26F software engineer in Bangalore. Casual Hinglish, yaar/na sometimes.
      Short replies, sometimes slangy. Never sound like a bot.
    extra_info: >
      Reality TV fan.

knowledge:
  static:
    - inline: >
        This app is about reality TV predictions.
      max_chars: 500
    - path: ./briefs/show_bible.md
      max_chars: 800
      extra_info: Cast and format only.
  tools:
    - name: show_context
      module: tools.my_app.show_context
      description: Returns stable show metadata for a show_id argument.
    - name: recent_episode
      module: tools.my_app.recent_episode
      description: Returns summary of the most recent aired episode.

logging:
  level: info                         # debug | info | warning | error
  file: ./logs/hypeagent.log           # rotated daily; default ~/.hypeagent/logs/
  console: true
```

### 4.1 Built-in targeting strategies (v1)

| `strategy` | Behavior |
| --- | --- |
| `random_with_comments_last_24h` | Filter `since_hours`, `min_comment_count`; uniform random pick |
| `recent` | Newest content first; first match with comments |
| `oldest_unanswered` | Content with fewest agent-account comments (connector tags own user_ids) |
| `allowlist` | `params.content_ids: [id1, id2]` only |

### 4.2 `extra_info` injection points (mandatory support)

| Config node | Injected into prompt as |
| --- | --- |
| root `extra_info` | `## Global` |
| `platform.extra_info` | `## Platform` |
| `llm.extra_info` | `## LLM style` |
| `run.extra_info` | `## Run rules` |
| `targeting.extra_info` | `## Targeting` |
| `personas.<id>.extra_info` | `## Persona extras` |
| `personas.<id>.brief` | `## Persona` |
| `knowledge.static[].extra_info` | `## Knowledge` |

---

## 5. Secrets schema (`secrets.local.yaml`)

Never committed. Loaded only at CLI runtime.

```yaml
llm:
  api_key: sk-or-v1-...

accounts:
  priya_blr:
    user_id: "t2_abc123"              # platform-specific
    token: "eyJ..."                   # Bearer token or Reddit refresh setup
    extra: {}                         # connector-specific (subreddit oauth etc.)
  rohan_del:
    user_id: "t2_def456"
    token: "eyJ..."
```

### 5.1 Account resolution

- Each `personas.<id>.account` must reference a key in `secrets.accounts`.
- Connector receives `AccountSecret` for the current agent only.
- v3 will add `auth_connector` types; v1 is token-only.

---

## 6. Platform connector contract

### 6.1 Abstract base class

```python
# hypeagent/platforms/base.py

class PlatformConnector(ABC):
    name: str

    def __init__(self, platform_config: PlatformConfig, account: AccountSecret, http: HttpConfig):
        ...

    @abstractmethod
    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        """Return candidate posts (v1: kind=post only)."""

    @abstractmethod
    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        """Return content + all comments (flat list with parent_id)."""

    @abstractmethod
    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        """POST comment/reply as current account. Raises PlatformError on failure."""

    def can_reply(
        self,
        ctx: RunContext,
        thread: Thread,
        parent: Comment | None,
        reply_depth_max: int,
    ) -> bool:
        """Default: depth check via parent chain. Override for membership rules."""

    def filter_candidates(
        self,
        ctx: RunContext,
        contents: list[Content],
        strategy: TargetingConfig,
    ) -> list[Content]:
        """Default: delegate to targeting registry. Override for platform-specific pre-filter."""
```

### 6.2 Connector registration

```python
# hypeagent/platforms/registry.py

BUILTIN_CONNECTORS = {
    "reddit": "hypeagent.platforms.reddit:RedditConnector",
}

def load_connector(name_or_path: str) -> type[PlatformConnector]:
    # "reddit" → builtin
    # "./platforms/my_app.py" → importlib load class MyAppConnector or first PlatformConnector subclass
```

### 6.3 Reddit reference connector (shipped)

**File:** `hypeagent/platforms/reddit.py`

| Method | Reddit API |
| --- | --- |
| `list_contents` | `GET /r/{subreddit}/new` + filter by `created_utc` |
| `get_thread` | `GET /comments/{id}` |
| `publish_comment` | `POST /api/comment` with `thing_id`, `text`, optional `parent` |

**Config params (platform section):**

```yaml
platform:
  connector: reddit
  base_url: https://oauth.reddit.com
  user_agent: hypeagent/1.0 (by u/yourbot)
  subreddit: test
```

**Secrets extra for Reddit:**

```yaml
accounts:
  bot1:
    user_id: t2_xxx
    token: <refresh_token>
    extra:
      client_id: ...
      client_secret: ...
```

---

## 7. Knowledge tools contract

### 7.1 Tool interface

```python
# hypeagent/knowledge/tools.py

class KnowledgeTool(ABC):
    name: str
    description: str

    @abstractmethod
    def run(self, ctx: RunContext, arguments: dict[str, Any]) -> str:
        """Return plain text for LLM context. Max 2000 chars enforced by core."""
```

User tools are Python modules referenced in config:

```python
# tools/my_app/show_context.py

DESCRIPTION = "Returns stable show metadata."

def run(ctx, arguments: dict) -> str:
    show_id = arguments.get("show_id", "default")
    return f"Show {show_id}: reality TV format, 12 contestants..."
```

Module must expose `run(ctx, arguments) -> str` and optional `DESCRIPTION`.

### 7.2 Built-in tools (v1)

| Tool | Module | Purpose |
| --- | --- | --- |
| `static_file` | `hypeagent.knowledge.builtins.static_file` | Read path from arguments or config |
| `short_term_memory` | `hypeagent.knowledge.builtins.short_term_memory` | Last N actions by persona from SQLite |

### 7.3 Agent tool-calling flow (v1)

1. Drafter receives thread + static knowledge summary.
2. LLM may output JSON tool request: `{"tool": "recent_episode", "arguments": {}}`.
3. Core executes tool, appends result to prompt, re-calls LLM once (max 2 tool rounds per action).
4. Dry-run logs tool call + result without executing publish.

---

## 8. SQLite schema (v1)

**Path:** `~/.hypeagent/hypeagent.db` (override: `--db ./hypeagent.db`)

```sql
-- schema_version
CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY
);

-- llm_usage: budget tracking
CREATE TABLE llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL  -- ISO8601 UTC
);

CREATE INDEX idx_llm_usage_created ON llm_usage(created_at);

-- runs: one row per CLI invocation
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  config_name TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  agents_total INTEGER NOT NULL,
  actions_proposed INTEGER NOT NULL DEFAULT 0,
  actions_published INTEGER NOT NULL DEFAULT 0,
  llm_cost_usd REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL  -- running | completed | failed | budget_exceeded
);

-- proposed_actions: audit trail
CREATE TABLE proposed_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  content_id TEXT NOT NULL,
  content_preview TEXT NOT NULL,
  parent_comment_id TEXT,
  parent_preview TEXT,
  draft_text TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0,  -- 0=no 1=yes
  platform_comment_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- agent_short_memory (v1 minimal; expanded v2)
CREATE TABLE agent_short_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  content_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  text_preview TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_agent_memory_agent ON agent_short_memory(agent_id, created_at DESC);

-- budget_totals: materialized for fast print
CREATE TABLE budget_totals (
  key TEXT PRIMARY KEY,  -- 'daily:2026-07-22' | 'total'
  cost_usd REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
```

---

## 9. LLM layer

### 9.1 `LLMClient`

```python
class LLMClient:
    def __init__(self, llm_config: LLMConfig, api_key: str, budget: BudgetGuard, db: Database):
        ...

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        run_id: str,
        agent_id: str,
    ) -> LLMResponse:
        """
        Calls OpenAI-compatible POST /chat/completions.
        Records usage in llm_usage + budget_totals.
        Raises BudgetExceededError if cap hit.
        """
```

### 9.2 Default provider

| Field | Default |
| --- | --- |
| `base_url` | `https://openrouter.ai/api/v1` |
| `model` | `openai/gpt-4o-mini` |
| Pricing | Estimated from OpenRouter response `usage` + static per-model table; fallback $0.000002/token blended |

### 9.3 Prompt templates

**System prompt (drafter):**

```text
You write social media comments as a real human persona.
Output ONLY the comment text. No quotes, no explanation.

{extra_info_blocks}

## Persona
{persona.brief}
City: {persona.city}
Languages: {persona.languages}

## Knowledge
{static_knowledge_summary}
{tool_results}

## Rules
- Match persona voice and language.
- Keep it short unless thread is serious.
- Do not break character.
- action_type: {comment|reply}
```

**User prompt (drafter):**

```text
## Post
Author: {content.author_display}
Text: {content.body}

## Comments
{formatted_thread}

Write one {action_type}.
```

---

## 10. Agent loop (v1)

### 10.1 `AgentRunner.run_all()`

```python
class AgentRunner:
    def run_all(self, mode: RunMode) -> RunResult:
        run_id = uuid4().hex
        for agent_id in config.run.agents:
            self.run_one_agent(run_id, agent_id, mode)
        return self.finalize(run_id)
```

### 10.2 `AgentRunner.run_one_agent()`

```text
1. Build RunContext for agent_id
2. connector = load_connector(platform.connector)
3. since = now() - targeting.params.since_hours
4. contents = connector.list_contents(ctx, since=since)
5. candidates = targeting_registry.apply(strategy, contents, ctx)
6. IF empty → log warning, skip agent
7. content = random.choice(candidates)
8. thread = connector.get_thread(ctx, content.id)
9. planner decides COMMENT vs REPLY from per_agent quotas
10. IF REPLY:
      eligible = comments where can_reply(depth <= reply_depth_max)
      IF empty → fallback to COMMENT or skip
      parent = random.choice(eligible)
11. static_knowledge = knowledge.static_loader.summarize(config)
12. tool_results = knowledge.tools.maybe_invoke(drafter, ctx, thread)
13. draft = drafter.draft(ctx, thread, action_type, parent, static_knowledge, tool_results)
14. proposed = ProposedAction(...)
15. db.save_proposed(proposed)
16. SWITCH mode:
      dry_run → log [DRY-RUN], no publish
      approve → approval.prompt(proposed) → publish if Y
      auto    → publish
17. IF published:
      comment = connector.publish_comment(...)
      db.save_published(...)
      short_term_memory.record(...)
18. budget_guard.check()
```

### 10.3 `Planner`

```python
class Planner:
    def decide(
        self,
        per_agent: PerAgentQuota,
        thread: Thread,
        ctx: RunContext,
    ) -> tuple[ActionType, Comment | None]:
        """
        v1 logic:
        - If replies quota > 0 and thread has comments → REPLY (random eligible parent)
        - Else if comments quota > 0 → COMMENT
        - Else skip
        """
```

### 10.4 `ApprovalPrompt`

```text
Agent: rohan_del (Delhi, Hinglish)
Action: REPLY

Post by @user123 (2h ago):
  "I think X will get evicted this week"

Replying to @other_user:
  "Same bro X is playing dirty"

Draft:
  "Arre bhai disagree 😂 X ki game strong hai"

Publish? [Y/n/e/q] (e=edit draft, q=quit run)
```

---

## 11. CLI specification

**Framework:** Typer  
**Global flags:** `--config PATH` (default `./hypeagent.yaml`), `--secrets PATH` (default `./secrets.local.yaml`), `--db PATH`, `--verbose`

### 11.1 Commands

| Command | Description |
| --- | --- |
| `hypeagent validate` | Parse config + secrets; verify connector/tools import; no network |
| `hypeagent dry-run` | Default run mode; log proposed actions; no writes |
| `hypeagent run` | Live run; mode from `--mode` flag |
| `hypeagent run --mode approve` | Prompt before each publish |
| `hypeagent run --mode auto` | Publish without prompt |
| `hypeagent usage print` | Print daily + total LLM spend and action counts |
| `hypeagent usage reset` | Reset `budget_totals` and optionally `llm_usage` (--confirm flag required) |
| `hypeagent cron-print` | Print suggested crontab lines for N runs/day |
| `hypeagent version` | Print package version |

### 11.2 `hypeagent validate` output

```text
✓ hypeagent.yaml schema valid
✓ secrets.local.yaml loaded (5 accounts)
✓ connector 'reddit' importable
✓ tools: show_context, recent_episode importable
✓ personas reference valid accounts
✓ budgets: daily=$2.00 total=$50.00
Ready.
```

### 11.3 `hypeagent cron-print`

```bash
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

```text
# Paste into crontab -e
0 9 * * * cd /path/to/project && hypeagent run --mode auto -c hypeagent.yaml -s secrets.local.yaml >> logs/cron.log 2>&1
0 13 * * * cd /path/to/project && hypeagent run --mode auto -c hypeagent.yaml -s secrets.local.yaml >> logs/cron.log 2>&1
0 18 * * * cd /path/to/project && hypeagent run --mode auto -c hypeagent.yaml -s secrets.local.yaml >> logs/cron.log 2>&1
0 22 * * * cd /path/to/project && hypeagent run --mode auto -c hypeagent.yaml -s secrets.local.yaml >> logs/cron.log 2>&1
```

### 11.4 `hypeagent usage print` output

```text
LLM usage (hypeagent.db)
  Today (2026-07-22):  $0.42 / $2.00 daily cap
  All time:            $12.18 / $50.00 total cap

Actions
  Today:  23 proposed, 18 published
  Runs:   4 completed today, 47 all time

Last run: 2026-07-22T18:02:11Z mode=approve status=completed
```

### 11.5 Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Config/secrets validation error |
| 2 | Budget exceeded |
| 3 | Platform API error |
| 4 | User quit during approval |
| 5 | Partial run failure |

---

## 12. Logging specification

**Format (file):**

```text
2026-07-22T19:02:14.123Z INFO  run_id=7a2f agent=priya_blr event=content_picked content_id=abc123 comment_count=3
2026-07-22T19:02:16.456Z DEBUG run_id=7a2f agent=priya_blr event=llm_call model=openai/gpt-4o-mini tokens_in=842 tokens_out=47 cost_usd=0.0021
2026-07-22T19:02:16.457Z INFO  run_id=7a2f agent=priya_blr event=dry_run action=reply content_id=abc123 draft="Haan yaar same feeling"
2026-07-22T19:02:17.000Z INFO  run_id=7a2f agent=rohan_del event=content_picked ...
```

**Rotation:** 10 MB × 5 files per log path.

---

## 13. Implementation phases

### Phase 0 — Scaffold (Week 1, Days 1–2)

**Deliverables:**
- `pyproject.toml` with dependencies: `typer`, `pydantic`, `pyyaml`, `httpx`, `openai` (compatible client), `python-dotenv`
- Package structure as §2
- `hypeagent version`, `hypeagent validate` (schema only)
- MIT LICENSE, README stub
- GitHub Actions: lint (ruff), typecheck (mypy), pytest

**Done when:** `pip install -e .` works; `hypeagent validate` parses example YAML.

---

### Phase 1 — Config, secrets, models (Week 1, Days 3–5)

**Deliverables:**
- Pydantic models for full `hypeagent.yaml` and `secrets.local.yaml` (§4, §5)
- `config/loader.py`, `config/secrets.py`
- Canonical models (§3)
- `examples/reddit/hypeagent.yaml` + `secrets.example.yaml`
- Unit tests: valid/invalid config cases

**Done when:** `hypeagent validate` passes on example; rejects missing account refs.

---

### Phase 2 — SQLite + usage (Week 2, Days 1–2)

**Deliverables:**
- `db/migrations.py` applies schema §8
- `UsageRepository`: record LLM usage, print, reset
- `hypeagent usage print`, `hypeagent usage reset --confirm`
- `BudgetGuard`: check daily/total before each LLM call

**Done when:** Usage persists across runs; reset clears totals.

---

### Phase 3 — LLM client (Week 2, Days 3–4)

**Deliverables:**
- `LLMClient` with OpenRouter default (§9)
- `prompts.py` with `extra_info` assembly
- Cost estimation + `BudgetExceededError`
- Unit tests with mocked HTTP

**Done when:** Single completion call records usage and respects caps.

---

### Phase 4 — HTTP + Reddit connector (Week 2, Day 5 – Week 3, Day 2)

**Deliverables:**
- `platforms/http_client.py`: timeouts, retries, user-agent header
- `platforms/base.py`, `platforms/registry.py`
- `platforms/reddit.py` full implementation (§6.3)
- Integration test against Reddit sandbox / recorded VCR fixtures

**Done when:** Connector lists posts, reads thread, publishes comment in test env.

---

### Phase 5 — Targeting (Week 3, Days 3–4)

**Deliverables:**
- Four strategies (§4.1)
- `targeting/registry.py`
- Unit tests per strategy

**Done when:** `random_with_comments_last_24h` filters correctly on fixture data.

---

### Phase 6 — Knowledge (Week 3, Day 5 – Week 4, Day 1)

**Deliverables:**
- `knowledge/static.py`: inline + file, `max_chars` truncation
- `knowledge/tools.py`: dynamic import, `run(ctx, args)`
- Builtins: `static_file`, `short_term_memory`
- Max 2 tool rounds per draft

**Done when:** Tool modules load from user `tools/` path relative to cwd.

---

### Phase 7 — Agent loop (Week 4, Days 2–4)

**Deliverables:**
- `Planner`, `Drafter`, `AgentRunner` (§10)
- Sequential multi-agent run
- `runs` + `proposed_actions` persistence

**Done when:** End-to-end dry-run produces N proposed actions in DB and logs.

---

### Phase 8 — Dry-run, approval, auto (Week 4, Day 5 – Week 5, Day 1)

**Deliverables:**
- `hypeagent dry-run` (default)
- `hypeagent run --mode approve|auto`
- `ApprovalPrompt` with content previews (§10.4)
- Edit draft inline (`e` key)

**Done when:** Founder can dry-run, approve one action, see it on Reddit.

---

### Phase 9 — Logging, cron-print, polish (Week 5, Days 2–3)

**Deliverables:**
- File logging with rotation (§12)
- `hypeagent cron-print`
- `examples/reddit/` complete working example
- README: quickstart &lt;2 hours

**Done when:** v1 acceptance criteria met (§16).

---

### Phase 10 — v1 release (Week 5, Days 4–5)

**Deliverables:**
- PyPI publish `hypeagent`
- CHANGELOG v1.0.0
- Integration test suite green
- Docs site or README sections: config reference, connector guide, tool guide

---

## 14. v2 scope (post-v1, fixed backlog)

| Feature | Spec |
| --- | --- |
| Actions | `react`, `dm`, `follow`, `create_post` |
| Content kinds | `take`, `thread`, `discussion` |
| Cross-session memory | `agent_long_memory` table; persona opinion summary field |
| Opinion consistency | `personas.<id>.stance` + inject past published texts |
| Python hooks | `hooks/before_pick`, `hooks/before_publish`, `hooks/after_publish` |
| Targeting | `keyword_match`, `tag_match`, custom plugin via `targeting.module` |
| Knowledge | `web_search`, `fetch_url` builtins |
| Platforms | Hacker News, Dev.to examples |
| Spoiler policy | `knowledge.spoiler_mode: strict\|warn\|off` |
| Posts without comments | `random_recent` strategy for seeding first comments |

---

## 15. v3 scope (fixed backlog)

| Feature | Spec |
| --- | --- |
| Auth connectors | `secrets.auth_type: token \| oauth_refresh \| service_account` |
| Impersonation | Optional `service_key` + `act_as_user_id` in connector |
| Event-driven | `hypeagent serve --webhook :8765` triggers run on POST |
| Multi-config | `hypeagent run --profile prod` reads `hypeagent.prod.yaml` |

---

## 16. v1 acceptance criteria

- [ ] `pip install hypeagent` provides CLI
- [ ] `hypeagent validate` validates config + secrets + imports
- [ ] `hypeagent dry-run` with Reddit example completes without writes
- [ ] `hypeagent run --mode approve` shows post/parent previews and publishes on Y
- [ ] `hypeagent run --mode auto` publishes without prompt
- [ ] `hypeagent usage print` and `usage reset --confirm` work
- [ ] `hypeagent cron-print` outputs valid crontab lines
- [ ] 50 agents in one config run sequentially without crash
- [ ] Daily and total LLM caps enforced
- [ ] Logs written to file with run_id and agent_id
- [ ] Custom connector loadable from `./platforms/my_app.py`
- [ ] Custom tools loadable from `./tools/...`
- [ ] Founder can complete Reddit quickstart in &lt;2 hours

---

## 17. Sample end-to-end flow (Reddit, 5 agents)

```bash
# 1. Install (use a venv per project)
mkdir -p my-reddit-seed && cd my-reddit-seed
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install hypeagent

# 2. Init from example
cp -r $(python -c "import hypeagent; import os; print(os.path.dirname(hypeagent.__file__))")/../examples/reddit/* .
cp secrets.example.yaml secrets.local.yaml
# Edit secrets.local.yaml with Reddit OAuth tokens

# 3. Validate
hypeagent validate

# 4. Dry-run (default)
hypeagent dry-run
# Review ./logs/hypeagent.log

# 5. Approval run
hypeagent run --mode approve

# 6. Auto via cron
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
# Paste output into crontab

# 7. Check spend
hypeagent usage print
```

---

## 18. Dependencies

```toml
[project]
name = "hypeagent"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12",
  "pydantic>=2.0",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "openai>=1.40",
]

[project.optional-dependencies]
reddit = ["praw>=7.7"]

[project.scripts]
hypeagent = "hypeagent.cli.main:app"
```

---

## 19. Testing strategy

| Layer | Tool | Coverage target |
| --- | --- | --- |
| Config schema | pytest | 100% valid/invalid cases |
| Targeting | pytest | Each strategy |
| Budget | pytest | Cap edge cases |
| LLM | pytest + httpx mock | Record/replay |
| Reddit connector | pytest + VCR | list, thread, comment |
| Agent loop | integration | dry-run full 3 agents |
| CLI | typer testing | All commands exit codes |

---

## 20. Security requirements

- Secrets file path logged never; tokens redacted in debug logs
- `secrets.local.yaml` in default `.gitignore` template
- HTTP client TLS verification on (no `verify=False`)
- User-agent required for all platform HTTP calls
- No telemetry / no upstream data collection
- Published content audit in SQLite for founder review

---

*This document is the single source of truth for hypeagent v1 implementation. v2/v3 items are scoped but not built until v1 acceptance criteria pass.*
