"""Unit tests for platform connector registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from hypeagent.platforms.base import PlatformConnector
from hypeagent.platforms.reddit import RedditConnector
from hypeagent.platforms.registry import ConnectorLoadError, load_connector


def test_load_builtin_reddit_connector() -> None:
    connector_cls = load_connector("reddit")
    assert connector_cls is RedditConnector
    assert connector_cls.name == "reddit"


def test_load_unknown_connector_raises() -> None:
    with pytest.raises(ConnectorLoadError, match="Unknown connector"):
        load_connector("not_a_platform")


def test_load_connector_from_file(tmp_path: Path) -> None:
    connector_file = tmp_path / "my_app.py"
    connector_file.write_text(
        """
from hypeagent.platforms.base import PlatformConnector

class MyAppConnector(PlatformConnector):
    name = "my_app"

    def list_contents(self, ctx, *, since):
        return []

    def get_thread(self, ctx, content_id):
        raise NotImplementedError

    def publish_comment(self, ctx, content_id, text, parent_comment_id):
        raise NotImplementedError
""",
        encoding="utf-8",
    )
    connector_cls = load_connector(str(connector_file))
    assert issubclass(connector_cls, PlatformConnector)
    assert connector_cls.name == "my_app"
