# Reddit seeding example

Two persona agents reply to posts in a subreddit using OpenRouter and Reddit OAuth.

## Prerequisites

- Python 3.11+
- [OpenRouter](https://openrouter.ai/) API key
- Reddit app credentials (script or web app) with OAuth tokens per account

## Setup (~15 minutes)

```bash
# From the repo root (development install)
pip install -e ".[dev]"

# Or copy this folder to your project
cp -r examples/reddit ./my-reddit-seed
cd my-reddit-seed
pip install hypeagent
```

Copy and edit secrets:

```bash
cp secrets.example.yaml secrets.local.yaml
# Set llm.api_key and per-account Reddit OAuth tokens
```

Edit `hypeagent.yaml`:

- Set `platform.subreddit` to your target subreddit (use `test` for sandbox)
- Set `platform.user_agent` with your Reddit username
- Adjust personas, budgets, and run schedule as needed

## Validate

```bash
hypeagent validate
```

Expected output ends with `Ready.`

## Dry run (no writes)

```bash
hypeagent dry-run
```

Review proposed replies in `./logs/hypeagent.log`.

## Approval run

```bash
hypeagent run --mode approve
```

Preview each draft and press `Y` to publish, `n` to skip, `q` to quit.

## Auto run via cron

```bash
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

Paste the output into `crontab -e`.

## Usage and budgets

```bash
hypeagent usage print
hypeagent usage reset --confirm   # clears spend totals
```

## Files

| File | Purpose |
| --- | --- |
| `hypeagent.yaml` | Agents, personas, targeting, budgets |
| `secrets.local.yaml` | API keys and account tokens (never commit) |
| `briefs/show_bible.md` | Static knowledge for the drafter |
| `tools/my_app/` | Custom knowledge tools referenced in config |
| `logs/hypeagent.log` | Rotated run logs (created on first run) |
