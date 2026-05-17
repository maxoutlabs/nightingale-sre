# 🐦 Nightingale SRE

> **Autonomous CI/CD Repair Agent** — detects, diagnoses, and fixes pipeline failures with zero human intervention.

![Nightingale Banner](banner.png)



[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GPT-4o](https://img.shields.io/badge/Powered%20by-GPT--4o-green)](https://openai.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/Dashboard-FastAPI-009688)](https://fastapi.tiangolo.com)

---

## What is Nightingale?

When your CI pipeline breaks at 3 AM, Nightingale wakes up so you don't have to.

It autonomously:
1. **Detects** the failure (GitHub webhook or manual trigger)
2. **Analyzes** root causes using GPT-4o with structured outputs
3. **Generates** a minimal, targeted fix (reflective loop — up to 3 attempts)
4. **Verifies** the fix in an isolated sandbox (never touches production)
5. **Decides** to auto-resolve or escalate based on a 5-factor confidence score
6. **Applies** the fix via a GitHub Pull Request (or direct write as fallback)
7. **Notifies** your team on Slack

All with a live web dashboard to monitor everything in real time.

---

## ⚡ Quick Start

```bash
# 1. Clone & install
git clone https://github.com/aadi-joshi/nightingale-sre.git
cd nightingale-sre
pip install -r requirements.txt

# 2. Set your OpenAI API key
export OPENAI_API_KEY='sk-...'          # Linux/macOS
$env:OPENAI_API_KEY = 'sk-...'          # PowerShell

# 3. Run the interactive demo
python main.py --demo

# 4. Or start the server + dashboard
python main.py --server
# → Dashboard: http://localhost:8000/
```

---

## Demo Scenarios

Nightingale ships with **three self-contained demo scenarios** — each is a real Python test file with a deliberate bug. No mocked data.

| # | Scenario | Bug | File |
|---|----------|-----|------|
| 1 | **Test Assertion Bug** | `assert subtract(2,2) == 1` (should be `== 0`) | `demo_repo/test_app.py` |
| 2 | **Broken Import** | `from collections import DefaultDict` (should be `defaultdict`) | `demo_repo/test_formatter.py` |
| 3 | **Logic Bug** | `return a` instead of `return b` in Fibonacci | `demo_repo/test_fibonacci.py` |

```bash
python main.py --demo              # Interactive picker (run 1, 2, 3, or all)
python main.py --scenario 1        # Run scenario 1 directly
python main.py --scenario 2        # Run scenario 2 directly
python main.py --scenario 3        # Run scenario 3 directly
```

Each scenario:
- Feeds real CI failure logs to GPT-4o
- Runs the actual broken tests in an isolated sandbox
- Generates and verifies a fix
- Reports full confidence breakdown

---

## Architecture

```
GitHub Webhook / Demo Trigger
        │
        ▼
   ┌─────────────┐
   │  Orchestrator│  ←── coordinates the whole pipeline
   └──────┬──────┘
          │
     ┌────┴────┐
     │ Context │  reads git history, file tree, failing file content
     └────┬────┘
          │
   ┌──────┴────────────────────┐
   │   ReflectiveReasoningLoop  │  up to 3 attempts
   │  ┌────────────────────┐   │
   │  │   MarathonAgent    │   │  GPT-4o structured outputs
   │  │   (fix generation) │   │
   │  └────────┬───────────┘   │
   │           │ FixPlan        │
   │  ┌────────┴───────────┐   │
   │  │  VerificationAgent │   │  runs tests in isolated sandbox
   │  └────────────────────┘   │
   │     if fails → reflect     │
   └────────────────────────────┘
          │ success
   ┌──────┴────────────┐
   │  ConfidenceScorer  │  5-factor weighted formula
   │  + gpt-4o-mini     │  risk classification
   └──────┬────────────┘
          │
   ┌──────┴──────────┐
   │ ResolutionEngine │  resolve or escalate
   └──────┬──────────┘
          │
     ┌────┴──────────────────┐
     │  GitHub PR  │  Slack  │
     │  + SQLite DB           │
     └───────────────────────┘
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| `MarathonAgent` | `nightingale/agents/marathon.py` | GPT-4o fix generation with reflection |
| `VerificationAgent` | `nightingale/agents/verifier.py` | Sandbox test runner |
| `Orchestrator` | `nightingale/core/orchestrator.py` | Full pipeline controller |
| `OpenAIClient` | `nightingale/core/openai_client.py` | GPT-4o + GPT-4o-mini API wrapper |
| `ConfidenceScorer` | `nightingale/analysis/confidence.py` | 5-factor weighted scoring |
| `GitHubPRCreator` | `nightingale/core/github_pr.py` | Automated PR creation |
| `SlackNotifier` | `nightingale/core/slack_notifier.py` | Slack notifications |
| `IncidentDatabase` | `nightingale/core/database.py` | SQLite persistence |
| `Sandbox` | `nightingale/core/sandbox.py` | Isolated test environment |
| Dashboard | `nightingale/static/index.html` | Live web UI |

---

## Confidence Scoring

Every auto-fix decision is backed by a transparent, auditable confidence formula:

```
confidence =
    35% × test_pass_ratio        (did ALL tests pass?)
  + 25% × inverse_blast_radius   (minimal files changed = safer)
  + 15% × attempt_penalty        (first-try fix = higher confidence)
  + 15% × risk_modifier          (gpt-4o-mini risk classification)
  + 10% × self_consistency       (model's own stated confidence)
```

**Threshold: 85%** — above this, Nightingale auto-resolves. Below, it escalates to a human with a full incident report.

---

## Configuration

All configuration lives in `config.yaml`. Secrets should be set via environment variables (never committed).

### `config.yaml`

```yaml
openai:
  model: "gpt-4o"           # Main reasoning model
  mini_model: "gpt-4o-mini" # Cheap risk classification

confidence:
  resolve_threshold: 0.85   # 0.0-1.0 — lower = auto-resolve more aggressively

github:
  token: ""                 # Or GITHUB_TOKEN env var
  repo: "owner/repo"        # Or GITHUB_REPO env var

slack:
  webhook_url: ""           # Or SLACK_WEBHOOK_URL env var
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | OpenAI API key (`sk-proj-...`) |
| `GITHUB_TOKEN` | ⬜ | GitHub personal access token (repo scope) — enables PR creation |
| `GITHUB_REPO` | ⬜ | Repository in `owner/repo` format |
| `SLACK_WEBHOOK_URL` | ⬜ | Slack incoming webhook URL — enables notifications |

### Setting env vars

```bash
# Linux/macOS
export OPENAI_API_KEY='sk-proj-...'
export GITHUB_TOKEN='ghp_...'
export GITHUB_REPO='myorg/myrepo'
export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'

# PowerShell
$env:OPENAI_API_KEY = 'sk-proj-...'
$env:GITHUB_TOKEN = 'ghp_...'
$env:GITHUB_REPO = 'myorg/myrepo'
$env:SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/...'
```

---

## Web Dashboard

Start the server and open `http://localhost:8000`:

```bash
python main.py --server
```

The dashboard provides:
- **Live incident feed** with real-time status stages (`Detected → Diagnosing → Fix Generated → Sandboxing → Resolved/Escalated`)
- **Click any incident** for full detail: root cause, fix diff, confidence breakdown, verification logs
- **Auto-resolve toggle** — disable autonomous fixing from the UI
- **Metrics panel** — total incidents, auto-resolved count, avg confidence, avg resolution time

### REST API

All dashboard data is available as a JSON API:

```
GET  /api/v1/incidents           List all incidents
GET  /api/v1/incidents/{id}      Incident detail + full report
GET  /api/v1/metrics             Aggregated metrics
GET  /api/v1/config              Current configuration
POST /api/v1/config/auto-resolve Toggle auto-resolve {"enabled": true/false}
GET  /health                     Health check
POST /webhook/github             GitHub webhook receiver
POST /incident                   Direct incident submission
GET  /docs                       Swagger UI
```

---

## GitHub Webhook Integration

Point your GitHub Actions webhook at Nightingale and it will automatically process CI failures:

1. Generate a webhook secret:
   ```bash
   openssl rand -hex 32
   ```

2. Add webhook in GitHub: `Settings → Webhooks → Add webhook`
   - Payload URL: `https://your-server:8000/webhook/github`
   - Content type: `application/json`
   - Secret: (your generated secret)
   - Events: `Workflow runs`, `Check runs`

3. Set the secret in `config.yaml`:
   ```yaml
   webhook:
     secret: "your-webhook-secret"
   ```

---

## GitHub PR Integration

When Nightingale auto-resolves an incident, instead of writing directly to disk, it opens a Pull Request:

```
[Nightingale] Auto-fix: Wrong expected value in test_subtract assertion

## Root Cause
The test asserts subtract(2, 2) == 1 but subtract(2, 2) returns 0...

## Confidence Score: 94%
| Factor              | Score | Weight |
|---------------------|-------|--------|
| Test Pass Ratio     | 1.00  | 35%    |
| Blast Radius        | 0.99  | 25%    |
...
```

Configure with `GITHUB_TOKEN` and `GITHUB_REPO` env vars. Falls back to direct file write if not set.

---

## Slack Notifications

Set `SLACK_WEBHOOK_URL` to receive notifications for every resolution or escalation:

**Resolved:**
```
✅ Nightingale: CI Failure Auto-Resolved
Incident: demo-1-20240115-143022
Repository: myorg/myrepo
Confidence: 94%

Root Cause: Wrong expected value in assert…
Fix: Changed assert subtract(2, 2) == 1 → == 0
🔗 View Pull Request
```

**Escalated:**
```
⚠️ Nightingale: CI Failure Escalated to Human
Confidence: 62% (below threshold)
Action Required: Please review manually
```

---

## Safety

Nightingale is built with safety as a first-class concern:

1. **Sandbox isolation** — fixes are always tested in a temporary copy of the repo. The original repo is SHA-256 hashed before and after to guarantee zero contamination.

2. **Confidence threshold** — auto-resolve only fires when confidence ≥ 85%. Below that, it escalates with a full report.

3. **Blast radius analysis** — changes to many files, or critical files (auth, database, deploy), are penalized in the confidence score.

4. **GitHub PR** — when configured, fixes go through code review before merging.

5. **Auto-resolve toggle** — can be disabled from the dashboard at any time.

---

## CLI Reference

```
python main.py --verify-api          Verify OpenAI API key (one request)
python main.py --self-check          Run 9-point system diagnostic
python main.py --demo                Interactive demo scenario picker
python main.py --scenario 1          Run scenario 1: test assertion bug
python main.py --scenario 2          Run scenario 2: broken import
python main.py --scenario 3          Run scenario 3: logic bug
python main.py --server              Start server + dashboard
python main.py --server --port 9000  Custom port
python main.py --demo --record-mode  Replay cached responses (no API calls)
```

---

## Project Structure

```
nightingale-sre/
├── main.py                          CLI entry point
├── config.yaml                      Configuration
├── requirements.txt                 Dependencies
│
├── nightingale/
│   ├── agents/
│   │   ├── marathon.py              GPT-4o fix generation (reflective loop)
│   │   └── verifier.py             Sandbox test runner
│   ├── analysis/
│   │   ├── blast_radius.py         File change impact analysis
│   │   ├── confidence.py           5-factor confidence scorer
│   │   └── reporter.py             Incident report generator
│   ├── api/
│   │   └── webhook.py              FastAPI: webhooks + dashboard REST API
│   ├── core/
│   │   ├── context.py              Repository context loader (GitPython)
│   │   ├── database.py             SQLite incident persistence
│   │   ├── github_pr.py            GitHub PR creator
│   │   ├── openai_client.py        OpenAI GPT-4o/mini client
│   │   ├── orchestrator.py         Main pipeline controller
│   │   ├── sandbox.py              Isolated test environment
│   │   ├── slack_notifier.py       Slack notifications
│   │   └── workflow_parser.py      GitHub Actions YAML parser
│   ├── demo/
│   │   └── scenario.py             Three demo scenarios
│   ├── static/
│   │   └── index.html              Web dashboard (dark theme, live updates)
│   └── types.py                    Pydantic data models
│
└── demo_repo/                       Demo "broken" repository
    ├── test_app.py                  Scenario 1: wrong assertion
    ├── test_formatter.py           Scenario 2: broken import
    ├── test_fibonacci.py           Scenario 3: logic bug
    └── .github/workflows/test.yml  CI config for demo repo
```

---

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run self-check
python main.py --self-check

# Run all demo scenarios
python main.py --demo  # then choose "A" for all

# Watch dashboard during a demo run
python main.py --server &
python main.py --demo
# → open http://localhost:8000
```

---

## License

MIT © 2025 Nightingale SRE Contributors

---

*Built for the GPT-4o Hackathon 2025. Nightingale demonstrates autonomous SRE agents: reliable, auditable, and safe by design.*
