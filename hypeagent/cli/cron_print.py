"""CLI cron-print command — suggested crontab lines (§11.3)."""

from __future__ import annotations

import re
from pathlib import Path

import typer

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_times(times: str) -> list[tuple[int, int]]:
    """Parse a comma-separated list of HH:MM times."""
    if not times.strip():
        msg = "At least one time is required (e.g. 09:00,13:00)"
        raise typer.BadParameter(msg)

    parsed: list[tuple[int, int]] = []
    for raw in times.split(","):
        token = raw.strip()
        if not token:
            continue
        match = _TIME_RE.match(token)
        if match is None:
            msg = f"Invalid time {token!r}; expected HH:MM (e.g. 09:00)"
            raise typer.BadParameter(msg)
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            msg = f"Time out of range: {token}"
            raise typer.BadParameter(msg)
        parsed.append((hour, minute))

    if not parsed:
        msg = "At least one time is required (e.g. 09:00,13:00)"
        raise typer.BadParameter(msg)
    return parsed


def build_cron_line(
    *,
    minute: int,
    hour: int,
    project_dir: Path,
    config_path: Path,
    secrets_path: Path,
    log_file: Path,
    mode: str,
) -> str:
    """Build a single crontab line for hypeagent run."""
    return (
        f"{minute} {hour} * * * cd {project_dir} && "
        f"hypeagent run --mode {mode} -c {config_path.name} -s {secrets_path.name} "
        f">> {log_file} 2>&1"
    )


def run_cron_print(
    *,
    times: str,
    timezone: str,
    project_dir: Path,
    config_path: Path,
    secrets_path: Path,
    log_file: Path,
    mode: str,
) -> None:
    """Print suggested crontab lines."""
    schedule = parse_times(times)
    typer.echo("# Paste into crontab -e")
    typer.echo(f"# Schedule timezone: {timezone}")
    typer.echo(f"CRON_TZ={timezone}")

    for hour, minute in schedule:
        line = build_cron_line(
            minute=minute,
            hour=hour,
            project_dir=project_dir,
            config_path=config_path,
            secrets_path=secrets_path,
            log_file=log_file,
            mode=mode,
        )
        typer.echo(line)
