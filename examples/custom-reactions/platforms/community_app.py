"""Example connector for an API with typed post and comment reactions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin

from hypeagent.config.schema import HttpConfig, PlatformConfig
from hypeagent.config.secrets_schema import AccountSecret
from hypeagent.models.action import (
    ActionTarget,
    ActionTargetKind,
    PublishResult,
)
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext
from hypeagent.platforms.base import (
    PlatformCapabilities,
    PlatformConnector,
    PlatformError,
    ReactionCapability,
)
from hypeagent.platforms.http_client import HttpClient

REACTION_TYPES = frozenset(
    {"agree", "disagree", "like", "insightful", "funny", "love", "sad"}
)


class CommunityAppConnector(PlatformConnector):
    """Map a representative community API to hypeagent's canonical models."""

    name = "community_app"

    def __init__(
        self,
        platform_config: PlatformConfig,
        account: AccountSecret,
        http: HttpConfig,
        *,
        http_client: HttpClient | None = None,
    ) -> None:
        super().__init__(platform_config, account, http)
        self._base_url = platform_config.base_url.rstrip("/") + "/"
        self._http = http_client or HttpClient(http, platform_config.user_agent)
        self._owns_http = http_client is None
        self._engagement: dict[tuple[ActionTargetKind, str], dict[str, Any]] = {}

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            reactions=ReactionCapability(
                target_kinds=frozenset(
                    {ActionTargetKind.CONTENT, ActionTargetKind.COMMENT}
                ),
                allowed_types=REACTION_TYPES,
                mode="toggle",
                max_per_entity=1,
            )
        )

    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        response = self._http.get(
            urljoin(self._base_url, "posts"),
            headers=self._auth_headers(),
            params={"since": since.isoformat()},
        )
        self._raise_for_status(response, "list_contents")
        payload = response.json()
        posts = payload.get("posts", [])
        if not isinstance(posts, list):
            raise PlatformError("Community API list_contents returned invalid posts")

        contents = [self._parse_content(post) for post in posts if isinstance(post, dict)]
        ctx.logger.debug("event=community_list_contents count=%d", len(contents))
        return contents

    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        response = self._http.get(
            urljoin(self._base_url, f"posts/{quote(content_id, safe='')}"),
            headers=self._auth_headers(),
        )
        self._raise_for_status(response, "get_thread")
        payload = response.json()
        post = payload.get("post")
        comments = payload.get("comments", [])
        if not isinstance(post, dict) or not isinstance(comments, list):
            raise PlatformError(f"Community API returned invalid thread for {content_id}")

        content = self._parse_content(post)
        parsed_comments = [
            self._parse_comment(comment, content.id)
            for comment in comments
            if isinstance(comment, dict)
        ]
        ctx.logger.debug(
            "event=community_get_thread content_id=%s comment_count=%d",
            content.id,
            len(parsed_comments),
        )
        return Thread(content=content, comments=parsed_comments)

    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        response = self._http.post(
            urljoin(self._base_url, "comments"),
            headers=self._auth_headers(),
            json={
                "postId": content_id,
                "parentId": parent_comment_id,
                "body": text,
            },
        )
        self._raise_for_status(response, "publish_comment")
        data = response.json().get("comment")
        if not isinstance(data, dict):
            raise PlatformError("Community API publish_comment returned no comment")
        comment = self._parse_comment(data, content_id)
        ctx.logger.info(
            "event=community_publish_comment content_id=%s comment_id=%s parent=%s",
            content_id,
            comment.id,
            parent_comment_id,
        )
        return comment

    def publish_reaction(
        self,
        ctx: RunContext,
        target: ActionTarget,
        reaction_type: str,
    ) -> PublishResult:
        entity_type = "post" if target.kind == ActionTargetKind.CONTENT else "message"
        response = self._http.post(
            urljoin(self._base_url, "reactions"),
            headers=self._auth_headers(),
            json={
                "entityType": entity_type,
                "entityId": target.id,
                "type": reaction_type,
            },
        )
        self._raise_for_status(response, "publish_reaction")
        payload = response.json()
        reaction = payload.get("reaction")
        if not isinstance(reaction, dict):
            raise PlatformError("Community API publish_reaction returned no reaction")

        self._engagement[(target.kind, target.id)] = {
            "myReaction": reaction.get("type", reaction_type),
            "reactionCounts": reaction.get("reactionCounts", {}),
        }
        ctx.logger.info(
            "event=community_publish_reaction target_kind=%s target_id=%s reaction=%s",
            target.kind.value,
            target.id,
            reaction_type,
        )
        object_id = reaction.get("id")
        return PublishResult(
            platform_object_id=str(object_id) if object_id is not None else None,
            raw=payload,
        )

    def current_engagement(
        self,
        ctx: RunContext,
        target: ActionTarget,
    ) -> dict[str, Any]:
        cached = self._engagement.get((target.kind, target.id))
        if cached is not None:
            return dict(cached)

        resource = "posts" if target.kind == ActionTargetKind.CONTENT else "messages"
        response = self._http.get(
            urljoin(self._base_url, f"{resource}/{quote(target.id, safe='')}"),
            headers=self._auth_headers(),
        )
        self._raise_for_status(response, "current_engagement")
        payload = response.json()
        entity = payload.get("post" if target.kind == ActionTargetKind.CONTENT else "message")
        if not isinstance(entity, dict):
            raise PlatformError(
                f"Community API current_engagement returned no {target.kind.value}"
            )
        engagement = self._remember_engagement(target.kind, target.id, entity)
        ctx.logger.debug(
            "event=community_current_engagement target_kind=%s target_id=%s reaction=%s",
            target.kind.value,
            target.id,
            engagement.get("myReaction"),
        )
        return dict(engagement)

    def _parse_content(self, data: dict[str, Any]) -> Content:
        content_id = str(data.get("id", ""))
        self._remember_engagement(ActionTargetKind.CONTENT, content_id, data)
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        return Content(
            id=content_id,
            kind="post",
            author_id=str(author.get("id", data.get("authorId", ""))),
            author_display=str(
                author.get("displayName", data.get("authorDisplay", ""))
            ),
            body=str(data.get("body", "")),
            created_at=self._parse_datetime(data.get("createdAt")),
            comment_count=int(data.get("commentCount", 0)),
            metadata={
                "myReaction": data.get("myReaction"),
                "reactionCounts": data.get("reactionCounts", {}),
            },
        )

    def _parse_comment(self, data: dict[str, Any], content_id: str) -> Comment:
        comment_id = str(data.get("id", ""))
        self._remember_engagement(ActionTargetKind.COMMENT, comment_id, data)
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        parent_id = data.get("parentId")
        return Comment(
            id=comment_id,
            content_id=str(data.get("postId", content_id)),
            parent_id=str(parent_id) if parent_id is not None else None,
            author_id=str(author.get("id", data.get("authorId", ""))),
            author_display=str(
                author.get("displayName", data.get("authorDisplay", ""))
            ),
            body=str(data.get("body", "")),
            created_at=self._parse_datetime(data.get("createdAt")),
            depth=int(data.get("depth", 0)),
            metadata={
                "myReaction": data.get("myReaction"),
                "reactionCounts": data.get("reactionCounts", {}),
            },
        )

    def _remember_engagement(
        self,
        kind: ActionTargetKind,
        target_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        engagement = {
            "myReaction": data.get("myReaction"),
            "reactionCounts": data.get("reactionCounts", {}),
        }
        self._engagement[(kind, target_id)] = engagement
        return engagement

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._account.token}"}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if not isinstance(value, str):
            raise PlatformError("Community API entity is missing createdAt")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlatformError(f"Invalid Community API createdAt: {value!r}") from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _raise_for_status(response: Any, operation: str) -> None:
        if response.status_code >= 400:
            body = response.text[:500]
            raise PlatformError(
                f"Community API {operation} failed ({response.status_code}): {body}"
            )
