# Custom typed-reactions example

This example shows a file-based connector that supports comments, replies, and
typed reactions on posts and comments. It is a reference API contract: adapt
`platforms/community_app.py` to your platform's routes and response fields.

## Run it

Start your community API at `http://localhost:4000`, then:

```bash
cd examples/custom-reactions
cp secrets.example.yaml secrets.local.yaml
# Edit secrets.local.yaml with the LLM key and account bearer token.
hypeagent validate
hypeagent dry-run
hypeagent run --mode approve
```

The bundled config chooses one weighted reaction per agent (`replies: 0` and
`action_priority: [reaction, ...]` so replies do not starve reactions). Approval
mode lets you accept, change, or skip the proposed reaction before it is
published.

## Expected API contract

All requests include `Authorization: Bearer <account token>`.

- `GET /api/posts?since=<ISO-8601>` returns `{"posts": [post, ...]}`.
- `GET /api/posts/{id}` returns `{"post": post, "comments": [comment, ...]}`.
- `GET /api/messages/{id}` returns `{"message": comment}`. This fallback is
  used only when the requested comment was not already cached from a thread.
- `POST /api/comments` accepts
  `{"postId": "...", "parentId": null, "body": "..."}` and returns
  `{"comment": comment}`.
- `POST /api/reactions` accepts
  `{"entityType": "post"|"message", "entityId": "...", "type": "agree"}` and
  returns `{"reaction": {"id": "...", "type": "agree"}}`.

A post has this shape:

```json
{
  "id": "post-1",
  "author": {"id": "user-1", "displayName": "Riya"},
  "body": "What did everyone think?",
  "createdAt": "2026-07-24T18:30:00Z",
  "commentCount": 1,
  "myReaction": null,
  "reactionCounts": {"agree": 3, "like": 8}
}
```

A comment uses the same author, body, time, and reaction fields, plus `postId`,
nullable `parentId`, and integer `depth`.

`myReaction` is important for toggle-style APIs. The connector caches it while
listing posts and loading threads; `current_engagement()` exposes it to the
planner so `skip_if_already_reacted: true` does not accidentally clear a
reaction by sending the same toggle again.

## Customize it

- Change `REACTION_TYPES` and `capabilities()` to match the platform vocabulary.
- Change `entityType` mapping in `execute()` if the API uses other target names.
- If reactions are set or additive rather than toggles, advertise the matching
  capability mode.
- Keep configured `engagement.reactions.types` and `targets` within the
  capability allowlists; `hypeagent validate` checks both.
