"""Reddit reference platform connector."""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from hypeagent.config.schema import HttpConfig, PlatformConfig
from hypeagent.config.secrets_schema import AccountSecret
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext
from hypeagent.platforms.base import PlatformConnector, PlatformError
from hypeagent.platforms.http_client import HttpClient

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


class RedditConnector(PlatformConnector):
    """Reddit OAuth connector using refresh tokens."""

    name = "reddit"

    def __init__(
        self,
        platform_config: PlatformConfig,
        account: AccountSecret,
        http: HttpConfig,
        *,
        http_client: HttpClient | None = None,
    ) -> None:
        super().__init__(platform_config, account, http)
        if not platform_config.subreddit:
            msg = "platform.subreddit is required for the reddit connector"
            raise PlatformError(msg)
        self._subreddit = platform_config.subreddit
        self._base_url = platform_config.base_url.rstrip("/") + "/"
        self._http = http_client or HttpClient(http, platform_config.user_agent)
        self._owns_http = http_client is None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def list_contents(self, ctx: RunContext, *, since: datetime) -> list[Content]:
        url = urljoin(self._base_url, f"r/{self._subreddit}/new")
        response = self._http.get(url, headers=self._auth_headers(), params={"limit": 100})
        self._raise_for_status(response, "list_contents")
        payload = response.json()
        children = payload.get("data", {}).get("children", [])
        contents: list[Content] = []
        for child in children:
            if child.get("kind") != "t3":
                continue
            content = self._parse_post(child.get("data", {}))
            if content.created_at >= since:
                contents.append(content)
        ctx.logger.debug(
            "event=reddit_list_contents subreddit=%s count=%d",
            self._subreddit,
            len(contents),
        )
        return contents

    def get_thread(self, ctx: RunContext, content_id: str) -> Thread:
        post_id = self._normalize_post_id(content_id)
        url = urljoin(self._base_url, f"comments/{post_id}")
        response = self._http.get(url, headers=self._auth_headers(), params={"limit": 500})
        self._raise_for_status(response, "get_thread")
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 1:
            msg = f"Unexpected Reddit thread response for {content_id}"
            raise PlatformError(msg)

        post_listing = payload[0].get("data", {}).get("children", [])
        if not post_listing:
            msg = f"Post not found: {content_id}"
            raise PlatformError(msg)

        post_data = post_listing[0].get("data", {})
        content = self._parse_post(post_data)

        comments: list[Comment] = []
        if len(payload) > 1:
            comment_children = payload[1].get("data", {}).get("children", [])
            comments = self._parse_comment_tree(comment_children, content.id)

        ctx.logger.debug(
            "event=reddit_get_thread content_id=%s comment_count=%d",
            content.id,
            len(comments),
        )
        return Thread(content=content, comments=comments)

    def publish_comment(
        self,
        ctx: RunContext,
        content_id: str,
        text: str,
        parent_comment_id: str | None,
    ) -> Comment:
        post_id = self._normalize_post_id(content_id)
        if parent_comment_id:
            parent = self._normalize_comment_id(parent_comment_id)
            form_data = {"parent": parent, "text": text}
        else:
            form_data = {"thing_id": f"t3_{post_id}", "text": text}

        url = urljoin(self._base_url, "api/comment")
        response = self._http.post(
            url,
            headers={**self._auth_headers(), "Content-Type": "application/x-www-form-urlencoded"},
            data=form_data,
        )
        self._raise_for_status(response, "publish_comment")
        payload = response.json()
        errors = payload.get("json", {}).get("errors") or []
        if errors:
            msg = f"Reddit publish_comment failed: {errors}"
            raise PlatformError(msg)

        comment_data = self._extract_published_comment(payload)
        if comment_data is None:
            msg = "Reddit publish_comment returned no comment data"
            raise PlatformError(msg)

        comment = self._parse_comment(comment_data, post_id, depth=0)
        ctx.logger.info(
            "event=reddit_publish_comment content_id=%s comment_id=%s parent=%s",
            post_id,
            comment.id,
            parent_comment_id,
        )
        return comment

    def _auth_headers(self) -> dict[str, str]:
        token = self._ensure_access_token()
        return {"Authorization": f"Bearer {token}"}

    def _ensure_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        client_id = self._account.extra.get("client_id")
        client_secret = self._account.extra.get("client_secret")
        if not client_id or not client_secret:
            msg = "Reddit account.extra must include client_id and client_secret"
            raise PlatformError(msg)

        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        response = self._http.post(
            REDDIT_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._account.token,
            },
        )
        self._raise_for_status(response, "oauth_token")
        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token or not isinstance(access_token, str):
            msg = "Reddit OAuth response missing access_token"
            raise PlatformError(msg)

        expires_in = int(payload.get("expires_in", 3600))
        self._access_token = access_token
        self._token_expires_at = time.time() + max(expires_in - 60, 0)
        return access_token

    def _parse_post(self, data: dict[str, Any]) -> Content:
        post_id = str(data.get("id", ""))
        title = str(data.get("title", ""))
        selftext = str(data.get("selftext", ""))
        body = title if not selftext else f"{title}\n\n{selftext}"
        created_utc = float(data.get("created_utc", 0))
        return Content(
            id=post_id,
            kind="post",
            author_id=str(data.get("author_fullname") or data.get("author", "")),
            author_display=str(data.get("author", "")),
            body=body,
            created_at=datetime.fromtimestamp(created_utc, tz=UTC),
            comment_count=int(data.get("num_comments", 0)),
            metadata={
                "name": data.get("name"),
                "subreddit": data.get("subreddit"),
                "permalink": data.get("permalink"),
                "url": data.get("url"),
            },
        )

    def _parse_comment_tree(
        self,
        children: list[dict[str, Any]],
        content_id: str,
        *,
        parent_id: str | None = None,
        depth: int = 0,
    ) -> list[Comment]:
        comments: list[Comment] = []
        for child in children:
            kind = child.get("kind")
            if kind == "more":
                continue
            if kind != "t1":
                continue
            data = child.get("data", {})
            comment = self._parse_comment(data, content_id, depth=depth, parent_id=parent_id)
            comments.append(comment)
            replies = data.get("replies")
            if isinstance(replies, dict):
                reply_children = replies.get("data", {}).get("children", [])
                comments.extend(
                    self._parse_comment_tree(
                        reply_children,
                        content_id,
                        parent_id=comment.id,
                        depth=depth + 1,
                    )
                )
        return comments

    def _parse_comment(
        self,
        data: dict[str, Any],
        content_id: str,
        *,
        depth: int,
        parent_id: str | None = None,
    ) -> Comment:
        comment_id = str(data.get("id", ""))
        parent_fullname = data.get("parent_id")
        resolved_parent = parent_id
        if (
            resolved_parent is None
            and isinstance(parent_fullname, str)
            and parent_fullname.startswith("t1_")
        ):
            resolved_parent = parent_fullname.removeprefix("t1_")

        created_utc = float(data.get("created_utc", 0))
        return Comment(
            id=comment_id,
            content_id=content_id,
            parent_id=resolved_parent,
            author_id=str(data.get("author_fullname") or data.get("author", "")),
            author_display=str(data.get("author", "")),
            body=str(data.get("body", "")),
            created_at=datetime.fromtimestamp(created_utc, tz=UTC),
            depth=depth,
            metadata={
                "name": data.get("name"),
                "permalink": data.get("permalink"),
            },
        )

    def _extract_published_comment(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        things = payload.get("json", {}).get("data", {}).get("things", [])
        for thing in things:
            if thing.get("kind") == "t1":
                data = thing.get("data")
                if isinstance(data, dict):
                    return data
        return None

    @staticmethod
    def _normalize_post_id(content_id: str) -> str:
        if content_id.startswith("t3_"):
            return content_id.removeprefix("t3_")
        return content_id

    @staticmethod
    def _normalize_comment_id(comment_id: str) -> str:
        if comment_id.startswith("t1_"):
            return comment_id
        return f"t1_{comment_id}"

    @staticmethod
    def _raise_for_status(response: Any, operation: str) -> None:
        if response.status_code >= 400:
            body = response.text[:500]
            msg = f"Reddit {operation} failed ({response.status_code}): {body}"
            raise PlatformError(msg)
