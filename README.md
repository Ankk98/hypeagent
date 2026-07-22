# hypeagent

Standalone CLI for running LLM-powered persona agents against social platforms.

Seed discussion on Reddit (and other platforms) with configurable personas, budgets, and approval workflows.

## Quick start

Install and validate the bundled Reddit example:

```bash
pip install -e ".[dev]"
cd examples/reddit
cp secrets.example.yaml secrets.local.yaml
# Edit secrets.local.yaml: OpenRouter API key + Reddit OAuth tokens

hypeagent validate
hypeagent dry-run
```

Logs are written to `./logs/hypeagent.log` with `run_id` and `agent_id` on each event.

## Commands

| Command | Description |
| --- | --- |
| `hypeagent validate` | Check config, secrets, connector, and tools |
| `hypeagent dry-run` | Propose actions without publishing |
| `hypeagent run --mode approve` | Prompt before each publish |
| `hypeagent run --mode auto` | Publish without prompt |
| `hypeagent usage print` | Show LLM spend and action counts |
| `hypeagent usage reset --confirm` | Reset budget totals |
| `hypeagent cron-print` | Print suggested crontab lines |
| `hypeagent version` | Print package version |

## Scheduled runs

```bash
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

Paste the output into `crontab -e`. Each line runs `hypeagent run --mode auto` and appends to `logs/cron.log`.

## Custom connectors and tools

- Platform connectors: drop modules in `./platforms/` — see [platforms/README.md](platforms/README.md)
- Knowledge tools: drop modules in `./tools/` — see [tools/README.md](tools/README.md)

## Reddit example

Full walkthrough: [examples/reddit/README.md](examples/reddit/README.md)

Typical flow:

1. Copy `examples/reddit` to your project directory
2. Configure `secrets.local.yaml` and `hypeagent.yaml`
3. `hypeagent validate` → `hypeagent dry-run` → `hypeagent run --mode approve`
4. `hypeagent cron-print` for unattended runs
5. `hypeagent usage print` to monitor spend

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy hypeagent
pytest
```

See [docs/implementation_plan.md](docs/implementation_plan.md) for the full specification.

## License

MIT
