# Nightingale Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     NIGHTINGALE AGENT                         │
│              Autonomous CI SRE System                         │
└──────────────────────────────────────────────────────────────┘

                         ┌─────────────┐
                         │  CI/CD Hook  │
                         │ (Webhook)    │
                         └──────┬──────┘
                                │ POST /webhook
                                ▼
                    ┌───────────────────────┐
                    │   Incident Listener   │
                    │   (listener.py)       │
                    │   Parses event JSON   │
                    └───────────┬───────────┘
                                │ IncidentEvent
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                             │
│                    (orchestrator.py)                           │
│                                                               │
│  1. Load repository context                                   │
│  2. Parse CI workflows for test commands                      │
│  3. Launch reflective reasoning loop                          │
│  4. Coordinate sandbox verification                           │
│  5. Calculate confidence & make decision                      │
│  6. Generate escalation report                                │
└───────────────────────────────┬───────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐
  │ Marathon Agent │  │   Sandbox    │  │  Decision Engine │
  │ (marathon.py)  │  │ (sandbox.py) │  │ (confidence.py)  │
  │                │  │              │  │                  │
  │ Reflective     │  │ SHA-256      │  │ 5-Factor Score:  │
  │ Reasoning Loop │  │ Integrity    │  │ · Test Ratio 35% │
  │ Max 3 Attempts │  │ Hashing      │  │ · Blast Rad  25% │
  │                │  │              │  │ · Attempt    15% │
  │ Feeds failure  │  │ Isolated     │  │ · Risk       15% │
  │ logs back for  │  │ Copy of Repo │  │ · Consistency10% │
  │ re-analysis    │  │              │  │                  │
  └───────┬───────┘  │ Test Runner  │  │ Threshold: 85%   │
          │          └──────────────┘  │ ≥85% → Resolve   │
          ▼                            │ <85% → Escalate   │
  ┌───────────────┐                    └──────────────────┘
  │  Gemini 3 API │
  │               │
  │ SDK: genai    │
  │ Model:        │
  │ gemini-3-     │
  │ flash-preview │
  │               │
  │ Structured    │
  │ JSON Output   │
  │ + Pydantic    │
  │ Validation    │
  └───────────────┘

Supporting Components:
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ Workflow     │  │ Blast Radius │  │ Escalation       │
│ Parser       │  │ Analyzer     │  │ Reporter         │
│              │  │              │  │                  │
│ Detects test │  │ Classifies   │  │ Markdown report  │
│ commands from│  │ file risk:   │  │ with confidence  │
│ GitHub       │  │ LOW/MED/HIGH │  │ breakdown &      │
│ Actions YAML │  │ /CRITICAL    │  │ verification     │
└──────────────┘  └──────────────┘  └──────────────────┘
```

## Data Flow

1. **CI failure** → Webhook receives event
2. **Parse** → Extract incident details (repo, branch, commit, logs)
3. **Context** → Load repository files, recent commits, failing test content
4. **Analyze** → Gemini 3 identifies root cause, proposes fix
5. **Sandbox** → Apply fix in isolated copy, run tests
6. **Verify** → Parse test output (pass/fail counts)
7. **Score** → Calculate 5-factor weighted confidence
8. **Decide** → Auto-resolve (≥85%) or escalate to human (<85%)
9. **Report** → Generate detailed Markdown incident report

## Key Design Principles

- **No fake logic** — All reasoning from live Gemini 3 API
- **Sandbox isolation** — Original repo never modified
- **Reflective loop** — Failed fixes feed back for re-analysis
- **Confidence-based decisions** — No blind auto-deployment
- **Single API key** — Clean, production-grade configuration
