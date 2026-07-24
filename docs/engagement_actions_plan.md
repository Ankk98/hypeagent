# Plan: Flexible engagement actions (reactions and beyond)

**Status:** Phase A + B implemented (core DSL + reactions config/planner/approval); Phases C–E not started  
**Scope:** Extend hypeagent beyond comment/reply so connectors can publish platform-native engagement (reactions, votes, likes, etc.) without hard-coding one app’s API into the core.  
**Primary motivator:** Social platforms commonly support non-text engagement such as typed reactions, likes, and votes on posts and comments.  
**Related:** Current v1 locks actions to `comment` / `reply` only ([implementation plan §1](./implementation_plan.md)).

---

## 1. Problem

### 1.1 Common platform needs

Organic feed activity is not limited to text comments. A typical platform may expose:

| Surface | Example API shape | Engagement |
| --- | --- | --- |
| Feed post | `POST /reactions` `{ entityType: "post", entityId, type }` | Typed reactions such as `agree`, `like`, or `insightful` |
| Discussion message | same endpoint, `entityType: "message"` | same types |
| Domain-specific entry | a platform-specific entity type | same types or a restricted subset |
| Post discussion | a platform-specific messages endpoint | text comments/replies |

Some platforms also expose scalar votes (`1/-1/0`) alongside emoji reactions. Connectors must map the canonical action to the API that powers the platform’s actual UI.

### 1.2 What hypeagent can do today

| Area | v1 behavior |
| --- | --- |
| `ActionType` | `comment`, `reply` only |
| Connector | `list_contents`, `get_thread`, `publish_comment` |
| Planner | quota: `per_agent.comments` / `per_agent.replies` |
| Drafter | always produces text |
| Approval UI | shows draft text |
| Persistence | `proposed_actions` assumes text drafts + `platform_comment_id` |

There is no first-class way to react, vote, follow, or do any non-text publish. Adding only a one-off `react` enum and a `publish_reaction` method would work for one integration but would paint Reddit (upvote/downvote), X (like), Discord (emoji), etc. into the same rigid shape.

### 1.3 Design goal

Keep the **core loop platform-agnostic**:

1. Discover content → pick target → choose an **action kind** the platform supports → optionally draft payload → approve → publish via connector.
2. Platforms declare **capabilities** and map them to their APIs.
3. Config selects **which capabilities to use** and quotas, without core knowing reaction emoji vocabularies or Reddit `t3_` IDs.

---

## 2. Design principles

1. **Capability-based, not app-based** — Core knows abstract action families (`text_comment`, `react`, `vote`, …). Connectors advertise what they support and how targets are addressed.
2. **Payloads are structured, not always text** — A reaction is `{ type: "agree" }`, not an LLM essay. Text actions keep `draft_text`.
3. **Connector owns vocabulary** — Allowed reaction types, whether reactions toggle, and whether one reaction per entity are platform rules. Core validates against connector-declared caps.
4. **Config selects intent** — YAML says “do N reactions per agent on posts”; connector maps that to `POST /reactions`.
5. **Backward compatible** — Existing Reddit + comment/reply configs keep working with zero changes.
6. **Opt-in LLM** — Reactions may use heuristics or a tiny LLM choice among allowed types; text drafting stays for comments/replies.
7. **Fail closed** — If config enables `react` but the connector does not advertise it, `validate` fails early.

---

## 3. Proposed architecture

### 3.1 Layering

```text
┌─────────────────────────────────────────────────────────────┐
│  hypeagent.yaml                                             │
│  run.per_agent: { comments, replies, reactions, … }         │
│  engagement: { reactions: { targets, types, strategy } }    │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│  Agent loop                                                 │
│  for each agent: list → filter → plan ActionSpec →          │
│  (optional draft) → approve → connector.execute(ActionSpec) │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
┌───────────────▼───────────────┐ ┌───────────▼───────────────┐
│  Planner / Drafter            │ │  PlatformConnector        │
│  picks ActionKind + target    │ │  capabilities()           │
│  builds ActionPayload         │ │  execute(ActionSpec)      │
│  text path still uses LLM     │ │  maps to HTTP / SDK       │
└───────────────────────────────┘ └───────────────────────────┘
```

### 3.2 Canonical models (core)

Replace the comment-only publish path with a small action DSL.

```python
class ActionKind(StrEnum):
    COMMENT = "comment"          # top-level text on content
    REPLY = "reply"              # text under a comment/message
    REACT = "react"              # emoji / reaction on a target
    VOTE = "vote"                # scalar vote (upvote/downvote/score)
    # Future (not in this milestone): FOLLOW, SHARE, POST_CREATE, ...

class ActionTargetKind(StrEnum):
    CONTENT = "content"          # post / thread root
    COMMENT = "comment"          # comment or discussion message
    # Future: USER, OPPORTUNITY, ...

@dataclass(frozen=True)
class ActionTarget:
    kind: ActionTargetKind
    id: str
    # optional display fields for approval UI
    preview: str | None = None

@dataclass(frozen=True)
class ActionPayload:
    """Kind-specific body. Exactly one semantic field set depending on kind."""
    text: str | None = None                 # COMMENT / REPLY
    reaction_type: str | None = None        # REACT — platform vocabulary
    vote_value: int | None = None           # VOTE — e.g. 1 / -1 / 0

@dataclass(frozen=True)
class ActionSpec:
    kind: ActionKind
    content_id: str                         # always anchored to a feed/content item
    target: ActionTarget                    # what we engage with
    payload: ActionPayload
    # metadata for prompts / approval
    rationale: str | None = None

@dataclass(frozen=True)
class PublishResult:
    platform_object_id: str | None          # comment id, reaction id, or None if toggle-clear
    raw: dict[str, Any] = field(default_factory=dict)
```

`ProposedAction` evolves to store `ActionSpec` (or flattened columns) instead of assuming `draft_text` + `parent_comment_id` only.

**Compatibility:** Keep `ActionType.COMMENT` / `REPLY` as aliases of `ActionKind` during migration; `publish_comment(...)` remains a default helper that builds `ActionSpec(COMMENT|REPLY)` and calls `execute`.

### 3.3 Connector capabilities

```python
@dataclass(frozen=True)
class ReactionCapability:
    target_kinds: frozenset[ActionTargetKind]   # CONTENT, COMMENT, ...
    allowed_types: frozenset[str]               # {"agree","like",...} or {"upvote"}
    mode: Literal["toggle", "set", "additive"]  # emoji APIs may toggle; Reddit vote=set
    max_per_entity: int | None = 1              # one active reaction per user+entity

@dataclass(frozen=True)
class PlatformCapabilities:
    text_comment: bool = True
    text_reply: bool = True
    reactions: ReactionCapability | None = None
    votes: ReactionCapability | None = None     # or separate VoteCapability
    # Future flags: follow, create_post, ...

class PlatformConnector(ABC):
    ...
    def capabilities(self) -> PlatformCapabilities:
        """Default: comments + replies only (today’s Reddit behavior)."""
        return PlatformCapabilities()

    def execute(self, ctx: RunContext, spec: ActionSpec) -> PublishResult:
        """Default: route COMMENT/REPLY to publish_comment; else raise PlatformError."""
        ...

    # Optional read helpers for planning
    def current_engagement(
        self, ctx: RunContext, target: ActionTarget
    ) -> dict[str, Any]:
        """e.g. myReaction, reactionCounts — default {}."""
        return {}
```

Connectors that support reactions override `capabilities()` and `execute()` (or override a dedicated `publish_reaction` that `execute` calls).

### 3.4 Why not only add `publish_reaction`?

A single method is fine as a **thin convenience**, but the core planner should call `execute(ActionSpec)` so:

- Vote vs emoji reaction can share planning logic with different payloads.
- Future actions (follow, join discussion) do not require new abstract methods forever (method explosion).
- Validation can compare `config.run` quotas against `capabilities()` in one place.

Recommended shape: **`execute` is required for new action kinds; `publish_comment` stays for backward compatibility.**

---

## 4. Config schema changes

### 4.1 Quotas (`run.per_agent`)

```yaml
run:
  agents: [riya_reacts, arjun_takes]
  per_agent:
    comments: 1
    replies: 1
    reactions: 1          # NEW — max reaction publishes per agent per run
    votes: 0              # NEW — optional scalar votes
  reply_depth_max: 2
  # Optional: how to choose among enabled kinds when multiple quotas remain
  action_priority: [reply, comment, reaction]   # NEW optional
```

Semantics (same spirit as today’s planner):

- For each agent, attempt **one** planned action per run iteration (current loop), consuming the matching quota.
- Multi-action-per-agent (comment **and** react on same post) is a **v2 enhancement**; v1 of this feature keeps “one action per agent per run” unless `per_agent` is raised and the loop gains an inner quota loop (see §8).

### 4.2 Engagement policy (new optional section)

```yaml
engagement:
  reactions:
    enabled: true
    targets: [content]              # content | comment | both
    # Restrict to a subset of connector-allowed types; omit = all allowed
    types: [agree, insightful, like]
    # How to pick type when LLM not used / as constraint for LLM
    strategy: weighted              # weighted | random | llm_choose | persona_affinity
    weights:                        # used when strategy=weighted
      agree: 0.4
      insightful: 0.3
      like: 0.3
    skip_if_already_reacted: true   # needs current_engagement()
    avoid_content_author_ids: []    # optional: don’t react to own posts
  votes:
    enabled: false
```

`validate` checks:

1. If `reactions > 0` or `engagement.reactions.enabled`, connector `capabilities().reactions` must be non-null.
2. Config `types` ⊆ connector `allowed_types`.
3. Config `targets` ⊆ connector `target_kinds`.

### 4.3 Example: custom emoji-reaction platform

```yaml
platform:
  connector: ./platforms/community_app.py
  base_url: http://localhost:4000
  user_agent: hypeagent/0.2 (community-app)

run:
  per_agent:
    comments: 1
    replies: 0
    reactions: 1

engagement:
  reactions:
    enabled: true
    targets: [content]
    types: [agree, insightful, like, funny]
    strategy: llm_choose
    skip_if_already_reacted: true
```

### 4.4 Example: Reddit (votes as “reactions” or votes)

Reddit has no emoji reactions on posts in the same sense; upvotes map cleanly to `votes`:

```yaml
run:
  per_agent:
    comments: 0
    replies: 1
    reactions: 0
    votes: 1

engagement:
  votes:
    enabled: true
    values: [1]                 # upvote only
    skip_if_already_voted: true
```

Reddit connector: `capabilities().votes = VoteCapability(allowed_values={1,-1,0}, mode="set")`.

---

## 5. Planner changes

### 5.1 Decision object

```python
@dataclass(frozen=True)
class PlannerDecision:
    spec: ActionSpec
```

### 5.2 Selection algorithm (proposed)

Given quotas remaining and thread/content state:

1. Build eligible kinds from quotas ∩ connector capabilities ∩ engagement config.
2. Apply `action_priority` (or default: `reply` → `comment` → `reaction` → `vote`).
3. For the first eligible kind that has a valid target:
   - **REPLY:** existing logic (eligible parents under `reply_depth_max`).
   - **COMMENT:** content root.
   - **REACT:** choose target (`content` and/or random comment); choose `reaction_type` via strategy; skip if `current_engagement` says already reacted.
   - **VOTE:** choose `vote_value` from config allowlist.
4. If none eligible → skip agent (same as today).

### 5.3 Choosing reaction type

| Strategy | Behavior | LLM cost |
| --- | --- | --- |
| `random` | Uniform among allowed types | None |
| `weighted` | Weighted random from config | None |
| `persona_affinity` | Map persona `extra_info` / brief tags → preferred types (connector or core table) | None |
| `llm_choose` | Short prompt: “pick one of {types} for this post”; JSON `{"reaction":"agree"}` | Low |

Default for cost-sensitive runs: `weighted`. Realityplay fan seeding can use `llm_choose` with `max_tokens` ~32.

### 5.4 Drafter

- **COMMENT / REPLY:** unchanged text drafting + tools.
- **REACT / VOTE:** no text draft; optional one-shot type/value selection; approval UI shows type/value instead of draft text.

---

## 6. Approval / dry-run UX

```text
Agent: riya_reacts (Mumbai, en, hinglish)
Action: REACT
Target: post beec47b9-… 
Preview: "Ram Kapoor is quietly running this whole season…"
Reaction: insightful

Publish? [Y/n/e/q]
```

For `e` on reactions: prompt to enter a new type (validated against allowlist), not free-form essay.

Dry-run logs:

```text
event=dry_run action=react content_id=… reaction=insightful
```

---

## 7. Persistence / usage

### 7.1 SQLite

Extend `proposed_actions` (new migration):

| Column | Purpose |
| --- | --- |
| `action_type` | already exists — add values `react`, `vote` |
| `draft_text` | nullable for non-text actions |
| `payload_json` | NEW — full `ActionPayload` + target |
| `target_kind` / `target_id` | NEW — or only inside JSON |
| `platform_comment_id` | rename conceptually to `platform_object_id` (keep column name for compat) |

### 7.2 Agent memory

Record reactions so agents don’t repeatedly toggle the same post:

```text
agent_short_memory: action_type=react, content_id=…, text_preview="insightful"
```

### 7.3 Budgets

Reactions with `weighted`/`random` consume **zero** LLM budget. `llm_choose` consumes a small completion — still under existing `BudgetGuard`.

---

## 8. Agent loop changes

Minimal change set:

1. After `filter_candidates` + pick content + `get_thread`, call updated `Planner.decide(...)`.
2. Branch on `decision.spec.kind`:
   - text → existing drafter
   - react/vote → engagement chooser (no long draft)
3. Approval uses kind-aware renderer.
4. Publish via `connector.execute(ctx, spec)` instead of only `publish_comment`.
5. Log `event=published` with kind-specific fields.

**Optional later:** inner loop so one agent can comment **and** react in one run when both quotas > 0 (`max_actions_per_agent_per_run`). Out of scope for the first reaction milestone.

---

## 9. Platform mappings

### 9.1 Generic typed-reaction API

| ActionSpec | HTTP |
| --- | --- |
| `COMMENT` / `REPLY` | Platform-specific comment endpoint |
| `REACT` on content | `POST /reactions` `{ entityType: "post", entityId, type }` |
| `REACT` on comment | `POST /reactions` `{ entityType: "message", entityId, type }` |
| `VOTE` (optional) | Platform-specific vote endpoint with `{ value }` |

```python
def capabilities(self) -> PlatformCapabilities:
    return PlatformCapabilities(
        text_comment=True,
        text_reply=True,
        reactions=ReactionCapability(
            target_kinds=frozenset({ActionTargetKind.CONTENT, ActionTargetKind.COMMENT}),
            allowed_types=frozenset({
                "agree", "disagree", "like", "insightful", "funny", "love", "sad",
            }),
            mode="toggle",
            max_per_entity=1,
        ),
    )
```

`current_engagement` for a post should read fields such as `myReaction` / `reactionCounts` from the platform’s content or feed response.

**Caution (toggle semantics):** Re-sending the same type clears the reaction. Planner must honor `skip_if_already_reacted` and prefer `current_engagement` over blind publish.

### 9.2 Reddit (reference)

| ActionSpec | HTTP |
| --- | --- |
| COMMENT / REPLY | existing `POST /api/comment` |
| VOTE | `POST /api/vote` with `id=t3_…` / `t1_…`, `dir=1|-1|0` |
| REACT | unsupported → `capabilities().reactions = None` |

### 9.3 Hypothetical future apps

| App pattern | Map to |
| --- | --- |
| Instagram-style likes only | `REACT` with `allowed_types={"like"}`, target CONTENT |
| Discord message reactions | `REACT` on COMMENT, additive mode, unicode emoji types |
| LinkedIn reactions | `REACT` with fixed enum (`like`,`celebrate`,…) |
| App with no engagement | capabilities default; config must keep `reactions: 0` |

---

## 10. Validation & errors

| Check | When | Failure |
| --- | --- | --- |
| Connector missing reaction capability | `hypeagent validate` | Exit 1 with clear message |
| Config type not in allowlist | validate | Exit 1 |
| Publish 4xx from platform | run | `PlatformError` → logged + printed in run summary (already improved) |
| Toggle accidentally cleared reaction | run | Treat as success but log `event=reaction_cleared`; prefer prevent via `current_engagement` |
| Empty draft for COMMENT | run | skip (existing) |

---

## 11. Testing plan

1. **Unit:** planner eligibility matrix (quotas × capabilities × config).
2. **Unit:** reaction type strategies (weighted distribution smoke test).
3. **Unit:** `ActionSpec` → Reddit and custom typed-reaction request builders (httpx mock).
4. **Unit:** validate rejects unknown reaction types.
5. **Integration:** custom connector against a local test backend — react on content, assert current reaction state; react on a comment; ensure toggle does not clear when skipped.
6. **Regression:** Reddit comment/reply dry-run + approve still green.
7. **CLI:** approval renderer for REACT; dry-run log lines; run summary errors printed.

---

## 12. Implementation phases

### Phase A — Core action DSL (no new product behavior yet) ✅

- Introduce `ActionKind`, `ActionSpec`, `PublishResult`, `PlatformCapabilities`.
- Add `execute()` defaulting to `publish_comment` for COMMENT/REPLY.
- Migrate loop/planner/approval to `ActionSpec` without config changes.
- Keep public CLI behavior identical.

### Phase B — Reactions ✅

- Config: `per_agent.reactions`, `engagement.reactions`.
- Planner + chooser strategies + approval UI.
- SQLite migration for payload fields.
- Docs: config reference + connector guide updates.

### Phase C — Typed-reaction connector support

- Implement `capabilities`, `execute` for REACT, `current_engagement`.
- Add a documented example YAML that enables reactions.
- Manual approve run: mix of comments + reactions visible on feed/post UI.

### Phase D — Votes + Reddit

- `engagement.votes` + Reddit `POST /api/vote`.
- Optional scalar-vote support for custom connectors.

### Phase E — Multi-action per agent / richer targets (later)

- Comment + react same run.
- React on takes (`opinion_entry`) as separate content kind or target kind.
- Follows, joins, etc. as new `ActionKind`s behind the same `execute` pipe.

---

## 13. Docs & examples to update when implementing

| Doc | Change |
| --- | --- |
| [config_reference.md](./config_reference.md) | `run.per_agent.reactions`, `engagement` section |
| [platforms/README.md](../platforms/README.md) | `capabilities()`, `execute()`, reaction contract |
| [implementation_plan.md](./implementation_plan.md) | Amend locked “v1 actions” note / add v1.1 section |
| [CHANGELOG.md](../CHANGELOG.md) | Entry under Unreleased when shipped |
| New example | `examples/custom-reactions/` with a mock or documented API contract |

---

## 14. Non-goals (this plan)

- Creating new posts / takes / opportunities via hypeagent.
- Browser automation or UI scraping for reactions.
- Server-side scheduling of reaction bursts (still cron + CLI).
- Guaranteeing human-like timing jitter beyond existing sequential agent loop (can add sleep jitter later in connector or loop).

---

## 15. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Toggle APIs clear reactions on repeat | `skip_if_already_reacted` + read `myReaction` before publish |
| LLM invents invalid reaction types | Strict JSON schema / allowlist filter; fallback to weighted |
| Config schema churn for early adopters | Additive fields with defaults `0` / `enabled: false` |
| Method explosion on connector ABC | Prefer `execute(ActionSpec)` over many `publish_*` abstracts |
| Agents dogpile same viral post | Existing targeting + memory; optional `max_agent_reactions_per_content` later |
| A platform feed mixes multiple entity types | Keep v1 content kind = post; add richer content kinds in Phase E |

---

## 16. Success criteria

1. A custom connector config can set `reactions: 1` and an approve-mode run shows a reaction in the platform’s user-facing engagement UI.
2. A Reddit-only config with no `engagement` section behaves exactly as today.
3. `hypeagent validate` catches “reactions enabled but connector cannot react”.
4. Adding a third platform’s reaction vocabulary requires **only** connector + YAML — no core changes to `ActionKind` (new types stay strings inside `ReactionCapability.allowed_types`).

---

## 17. Open questions (decide during Phase B)

1. **One action vs many per agent per run** — Should a run support comment+reaction by the same agent in one invocation?
2. **React on comments by default?** — Higher noise; recommend `targets: [content]` first.
3. **Should `llm_choose` share the main model or a cheaper override?** — e.g. `engagement.reactions.model`.
4. **Rename DB column `platform_comment_id` → `platform_object_id` now or later?** — Prefer additive nullable + dual-write reading for one release.
5. **Treat legacy post votes as `vote` or as `react` with types `up`/`down`?** — Prefer separate `vote` for Reddit parity.

---

## 18. Suggested first PR slice

1. Phase A refactor to `ActionSpec` / `execute` (behavior-preserving).
2. Phase B config + planner for reactions (dry-run only).
3. Phase C custom typed-reaction connector + local manual approve test.

That sequence lands architecture flexibility before platform-specific HTTP details, and keeps Reddit green throughout.
