# Reddit seeding example

Two persona agents reply to posts in a subreddit using OpenRouter and Reddit OAuth.

## Prerequisites

- Python 3.11+
- A virtual environment (venv) for the project — see setup below
- [OpenRouter](https://openrouter.ai/) API key
- Reddit app credentials (script or web app) with OAuth tokens per account

## Setup (~15 minutes)

```bash
# Create project directory and venv
mkdir -p my-reddit-seed && cd my-reddit-seed
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# From PyPI
pip install hypeagent
cp -r "$(python -c "import hypeagent, os; print(os.path.dirname(hypeagent.__file__))")/../examples/reddit"/* .

# Or clone the repo for development
# git clone https://github.com/Ankk98/hypeagent.git && cd hypeagent
# python3 -m venv .venv && source .venv/bin/activate
# pip install -e ".[dev]" && cd examples/reddit
```

Keep the venv activated whenever you run `hypeagent` commands in this directory.

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
source .venv/bin/activate   # Windows: .venv\Scripts\activate
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

Paste the output into `crontab -e`. Use the full path to `.venv/bin/hypeagent` in crontab lines so scheduled jobs do not require shell activation.

## Votes (optional)

Reddit upvotes are scalar votes, not emoji reactions. To upvote posts instead of
replying, set:

```yaml
run:
  per_agent:
    comments: 0
    replies: 0
    votes: 1
  action_priority: [vote, reply, comment]

engagement:
  votes:
    enabled: true
    targets: [content]
    values: [1]
    skip_if_already_voted: true
```

Then `hypeagent validate` and `hypeagent dry-run` as usual.

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
