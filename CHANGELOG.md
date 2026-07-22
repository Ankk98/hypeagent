# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-22

First alpha release of hypeagent — a standalone CLI for running LLM-powered persona agents against social platforms.

> **Alpha:** APIs, config schema, and CLI behavior may change before v1.0.

### Added

- **CLI** — `validate`, `dry-run`, `run` (`--mode approve|auto`), `usage print`, `usage reset`, `cron-print`, and `version`
- **Config** — `hypeagent.yaml` with Pydantic validation; `secrets.local.yaml` for API keys and account tokens
- **LLM** — OpenRouter and OpenAI-compatible providers with daily/total USD budget caps
- **Storage** — SQLite at `~/.hypeagent/hypeagent.db` for usage, runs, proposed actions, and short-term memory
- **Reddit connector** — Reference `PlatformConnector` with OAuth refresh tokens
- **Targeting** — `random_with_comments_last_24h`, `recent`, `oldest_unanswered`, and `allowlist` strategies
- **Knowledge** — Static inline/file briefs plus user-defined tools with up to two LLM tool rounds per action
- **Agent loop** — Sequential multi-agent runs with comment/reply planning and draft generation
- **Publish modes** — `dry-run` (default), interactive `approve`, and unattended `auto`
- **Logging** — Rotating file logs with structured `run_id` and `agent_id` fields
- **Examples** — Working Reddit quickstart under `examples/reddit/`
- **Extensibility** — Custom platform connectors (`./platforms/`) and knowledge tools (`./tools/`)

### Security

- Secrets paths and tokens are never logged; TLS verification is always enabled for HTTP calls.

[0.1.0]: https://github.com/Ankk98/hypeagent/releases/tag/v0.1.0
