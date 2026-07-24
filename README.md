# hypeagent

CLI based tool for running LLM-powered persona agents on social platforms.

> **Alpha (v0.1):** Early release — expect breaking changes before v1.0.

Seed discussion on platforms like Reddit with configurable personas, budgets, and approval workflows.

## Install

Use a virtual environment (recommended for every project):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install hypeagent
```

For Reddit OAuth development: `pip install hypeagent[reddit]`

## Quick start

Create a project directory with a venv, copy the bundled Reddit example, and validate:

```bash
mkdir -p my-reddit-seed && cd my-reddit-seed
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install hypeagent

cp -r "$(python -c "import hypeagent, os; print(os.path.dirname(hypeagent.__file__))")/../examples/reddit"/* .
cp secrets.example.yaml secrets.local.yaml
# Edit secrets.local.yaml: OpenRouter API key + Reddit OAuth tokens

hypeagent validate
hypeagent dry-run
```

Or clone the repo for development:

```bash
git clone https://github.com/Ankk98/hypeagent.git
cd hypeagent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cd examples/reddit
cp secrets.example.yaml secrets.local.yaml
hypeagent validate
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

## Documentation

| Guide | Description |
| --- | --- |
| [Config reference](docs/config_reference.md) | Full `hypeagent.yaml` and secrets schema |
| [Connector guide](platforms/README.md) | Build a custom `PlatformConnector` |
| [Tool guide](tools/README.md) | Build custom knowledge tools |
| [Engagement actions plan](docs/engagement_actions_plan.md) | Draft: reactions/votes via capability-based actions |
| [Reddit example](examples/reddit/README.md) | End-to-end quickstart |
| [Typed-reactions example](examples/custom-reactions/README.md) | Custom connector with post/comment reactions |
| [CHANGELOG](CHANGELOG.md) | Release history |

## Scheduled runs

Activate your project venv, then generate crontab lines:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

Paste the output into `crontab -e`. Each line runs `hypeagent run --mode auto` and appends to `logs/cron.log`.

For cron, use the venv binary so the job does not depend on an interactive shell, e.g. replace `hypeagent` with `/path/to/my-reddit-seed/.venv/bin/hypeagent` in the printed lines.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check .
mypy hypeagent
pytest
python -m build
```

See [docs/implementation_plan.md](docs/implementation_plan.md) for the full specification.

## License

MIT
