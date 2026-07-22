"""Unit tests for cron-print."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from hypeagent.cli.cron_print import build_cron_line, parse_times


def test_parse_times_accepts_comma_separated() -> None:
    assert parse_times("09:00,13:00,18:00,22:00") == [
        (9, 0),
        (13, 0),
        (18, 0),
        (22, 0),
    ]


def test_parse_times_rejects_invalid() -> None:
    with pytest.raises(typer.BadParameter, match="Invalid time"):
        parse_times("9am")


def test_build_cron_line_format() -> None:
    line = build_cron_line(
        minute=0,
        hour=9,
        project_dir=Path("/path/to/project"),
        config_path=Path("hypeagent.yaml"),
        secrets_path=Path("secrets.local.yaml"),
        log_file=Path("logs/cron.log"),
        mode="auto",
    )
    assert line == (
        "0 9 * * * cd /path/to/project && "
        "hypeagent run --mode auto -c hypeagent.yaml -s secrets.local.yaml "
        ">> logs/cron.log 2>&1"
    )
