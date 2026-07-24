# Use hypeagent in another project

Step-by-step: add hypeagent as a **declared dependency**, commit the connector and config to the product repo, and keep only secrets / venv / logs out of git.

hypeagent is a **CLI + config project**, not something you import into a Node/Java backend. You still give it its own Python venv, but the project files live in the same git repo as the product (for example under `seed/hypeagent/`).

Do **not** put the setup under a catch-all ignored folder like `.local/` — connectors, YAML, briefs, and tools should be reviewable and shareable like any other code.

## What gets committed vs ignored

| Commit | Gitignore |
| --- | --- |
| `requirements.txt` (or `pyproject.toml`) with `hypeagent` | `.venv/` |
| `hypeagent.yaml` | `secrets.local.yaml` |
| `secrets.example.yaml` | `logs/` |
| `platforms/*.py` (custom connector) | `__pycache__/`, `*.pyc` |
| `briefs/`, `tools/` | |
| `README.md` (how to run) | |

## Prerequisites

- Python **3.11+**
- An [OpenRouter](https://openrouter.ai/) API key (or another OpenAI-compatible endpoint)
- Platform credentials (Reddit OAuth, or JWTs / tokens for your own API)

Assume sibling clones when developing the library itself:

```text
~/repos/
  hypeagent/       # library (optional if you only install from PyPI)
  resume-maker/    # product repo — seeding lives here under seed/hypeagent/
```

## 1. Create a committed project directory

From the product repo root (example: `resume-maker`):

```bash
cd /path/to/resume-maker
mkdir -p seed/hypeagent
cd seed/hypeagent
```

Add ignore rules in that directory (or the repo root `.gitignore`):

```bash
cat >> /path/to/resume-maker/.gitignore <<'EOF'

# hypeagent (seed/hypeagent)
seed/hypeagent/.venv/
seed/hypeagent/secrets.local.yaml
seed/hypeagent/logs/
seed/hypeagent/**/__pycache__/
EOF
```

## 2. Declare the dependency and install

### Option A — PyPI (recommended for the product repo)

```bash
cd /path/to/resume-maker/seed/hypeagent

cat > requirements.txt <<'EOF'
# Prefer PyPI once published: hypeagent>=0.2.0
# Reactions / ActionSpec live on branch v0.2 until merged to main.
hypeagent @ git+https://github.com/Ankk98/hypeagent.git@v0.2
EOF

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

Commit `requirements.txt` with the rest of the seeding tree.

### Option B — Editable local clone (library development only)

While hacking on hypeagent next door, install editable **on top of** the declared dep (do not commit a machine-specific path into `requirements.txt`):

```bash
cd /path/to/resume-maker/seed/hypeagent
source .venv/bin/activate
pip install -e /path/to/hypeagent
# Reddit: pip install -e "/path/to/hypeagent[reddit]"
```

After finishing local library work, switch back to the pinned package:

```bash
pip install -r requirements.txt --force-reinstall
```

### Confirm

```bash
hypeagent version
which hypeagent   # .../seed/hypeagent/.venv/bin/hypeagent
```

## 3. Scaffold config and connector (then commit)

### Path A — Reddit (bundled example)

```bash
# venv active, cwd = seed/hypeagent
cp -r "$(python -c "import hypeagent, os; print(os.path.dirname(hypeagent.__file__))")/../examples/reddit"/* .

cp secrets.example.yaml secrets.local.yaml   # local only; not committed
```

Edit `hypeagent.yaml` and fill `secrets.local.yaml`. Ensure `requirements.txt` includes `hypeagent[reddit]` (or install that extra once).

### Path B — Your own API (custom connector)

```bash
cp -r "$(python -c "import hypeagent, os; print(os.path.dirname(hypeagent.__file__))")/../examples/custom-reactions"/* .

cp secrets.example.yaml secrets.local.yaml
# Adapt platforms/*.py to your API, then edit hypeagent.yaml
```

Target layout (everything except ignore-listed paths is committed):

```text
seed/hypeagent/
  README.md
  requirements.txt
  hypeagent.yaml
  secrets.example.yaml      # committed template
  secrets.local.yaml        # gitignored — real keys
  platforms/
    my_app.py               # committed connector
  briefs/
  tools/
  logs/                     # gitignored
  .venv/                    # gitignored
```

Point config at the connector:

```yaml
platform:
  connector: ./platforms/my_app.py
  base_url: http://localhost:4000
  user_agent: hypeagent/0.1 (my-app-local)
```

See [Connector guide](../platforms/README.md) and [Config reference](config_reference.md).

### First commit

```bash
cd /path/to/resume-maker
git add seed/hypeagent
git status   # confirm secrets.local.yaml and .venv are NOT staged
# git commit when ready
```

## 4. Fill secrets (local only)

```bash
cd seed/hypeagent
cp secrets.example.yaml secrets.local.yaml
# Edit secrets.local.yaml — never commit this file
```

Minimum shape:

```yaml
llm:
  api_key: sk-or-v1-...

accounts:
  some_persona:
    user_id: "..."
    token: "..."
```

Account keys must match `personas.*.account` in `hypeagent.yaml`.

## 5. Day-to-day commands

```bash
cd /path/to/resume-maker/seed/hypeagent
source .venv/bin/activate
```

| Step | Command | What it does |
| --- | --- | --- |
| Check setup | `hypeagent validate` | Config, secrets, connector, tools |
| Preview only | `hypeagent dry-run` | Propose actions; no publish |
| Manual publish | `hypeagent run --mode approve` | Prompt before each write |
| Unattended | `hypeagent run --mode auto` | Publish without prompt |
| Spend | `hypeagent usage print` | LLM + action totals |
| Reset spend | `hypeagent usage reset --confirm` | Clear budget counters |

Logs: `./logs/hypeagent.log`.

From another cwd:

```bash
hypeagent \
  -c /path/to/resume-maker/seed/hypeagent/hypeagent.yaml \
  -s /path/to/resume-maker/seed/hypeagent/secrets.local.yaml \
  validate
```

## 6. Schedule with cron

```bash
source .venv/bin/activate
hypeagent cron-print --times "09:00,13:00,18:00,22:00" --timezone Asia/Kolkata
```

Paste into `crontab -e`. Prefer the venv binary:

```text
/path/to/resume-maker/seed/hypeagent/.venv/bin/hypeagent
```

## 7. Update the dependency later

Bump the pin in `requirements.txt`, then:

```bash
cd /path/to/resume-maker/seed/hypeagent
source .venv/bin/activate
pip install -U -r requirements.txt
```

Commit the updated `requirements.txt` so teammates get the same version.

---

## Worked example: `resume-maker`

### One-time (committed tree)

```bash
cd /home/ankk98/repos/resume-maker
mkdir -p seed/hypeagent
cd seed/hypeagent

cat > requirements.txt <<'EOF'
hypeagent @ git+https://github.com/Ankk98/hypeagent.git@v0.2
EOF

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Add platforms/realityplay.py, hypeagent.yaml, briefs/, tools/ (commit these)
cp secrets.example.yaml secrets.local.yaml
# Fill OpenRouter key + account JWTs locally
```

Ensure `.gitignore` covers `.venv/`, `secrets.local.yaml`, and `logs/` under `seed/hypeagent/`, then commit the rest.

Start the product API:

```bash
cd /home/ankk98/repos/resume-maker/apps/backend
./gradlew bootRun
# health: http://localhost:4000/health
```

Set `platform.base_url` to that origin (backend URL, not a Next.js proxy).

### Every run

```bash
cd /home/ankk98/repos/resume-maker/seed/hypeagent
source .venv/bin/activate

hypeagent validate
hypeagent dry-run
hypeagent run --mode approve
```

### Teammate / CI bootstrap

```bash
cd seed/hypeagent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp secrets.example.yaml secrets.local.yaml
# fill secrets, then:
hypeagent validate
```

### Prod

Change `platform.base_url` to the deployed API origin and use production tokens in the local (or host-secret) `secrets.local.yaml` — still never commit secrets.

---

## Checklist

1. [ ] `seed/hypeagent/` (or similar) created **in the product repo**
2. [ ] `requirements.txt` declares `hypeagent` and is committed
3. [ ] `.gitignore` covers `.venv/`, `secrets.local.yaml`, `logs/`
4. [ ] Connector, `hypeagent.yaml`, `secrets.example.yaml`, briefs/tools committed
5. [ ] venv created; `pip install -r requirements.txt`
6. [ ] `secrets.local.yaml` filled locally
7. [ ] `hypeagent validate` → `Ready.`
8. [ ] `hypeagent dry-run` reviewed; then `run --mode approve` / `auto` / cron

## Related docs

| Guide | When |
| --- | --- |
| [Config reference](config_reference.md) | Full YAML schema |
| [Connector guide](../platforms/README.md) | Custom `PlatformConnector` |
| [Tool guide](../tools/README.md) | Custom knowledge tools |
| [Reddit example](../examples/reddit/README.md) | Reddit end-to-end |
| [Typed-reactions example](../examples/custom-reactions/README.md) | Custom API + reactions |
