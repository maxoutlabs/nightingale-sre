# Nightingale Safety & Blast Radius Mitigation

## Core Safety Philosophy

Nightingale is designed with **defense in depth** - multiple safety layers ensure that autonomous repairs cannot cause harm even in edge cases.

## Safety Layers

### 1. Sandbox Isolation

All code changes are tested in an isolated sandbox environment:

```
┌─────────────────────────────────────────────┐
│              PRODUCTION REPO                │
└─────────────────────────────────────────────┘
                    │ (read-only)
                    ▼
┌─────────────────────────────────────────────┐
│               SANDBOX                        │
│  ┌─────────────────────────────────────┐    │
│  │  Copy of repo (no .git, no secrets) │    │
│  │  - Changes applied here only        │    │
│  │  - Tests run in isolation           │    │
│  │  - Cleaned up after each run        │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

**Guarantees:**
- Production code is NEVER modified directly
- Each attempt starts fresh
- Sandbox is deleted after processing

### 2. Blast Radius Analysis

Every proposed change is analyzed for impact:

```python
# Risk Classification
CRITICAL: auth, security, database, migrations
HIGH:     core/, models/, main application files
MEDIUM:   utilities, helpers, configs
LOW:      tests, documentation, examples
```

**Scoring:**
- `inverse_blast_radius = 1 - (files_changed / total_files)`
- Fewer files changed = higher score = more confidence

**Thresholds:**
- Cannot auto-resolve if blast radius > 70%
- Cannot auto-resolve if CRITICAL files are modified

### 3. Confidence-Based Escalation

The system ONLY auto-resolves when confidence exceeds **85%**:

```
CONFIDENCE 90%+ → AUTO-RESOLVE (with verification)
CONFIDENCE 85-89% → AUTO-RESOLVE (conservative)
CONFIDENCE 60-84% → ESCALATE (human review required)
CONFIDENCE <60% → ABORT (too risky)
```

### 4. Multi-Attempt Penalty

Each additional attempt reduces confidence:

| Attempt | Penalty Factor |
|---------|---------------|
| 1st     | 1.0 (no penalty) |
| 2nd     | 0.7 (-30%) |
| 3rd     | 0.4 (-60%) |

This ensures that repeated failures lead to escalation.

### 5. Verification-First Design

Fixes are NEVER applied to production without verification:

1. Generate fix in sandbox
2. Run ALL test commands
3. Parse test results (pass/fail/total)
4. Only proceed if tests pass

### 6. File Type Guards

Certain file patterns trigger automatic escalation:

- `.env`, `credentials`, `secrets` → ALWAYS ESCALATE
- `migration`, `schema` → ALWAYS ESCALATE
- `deploy`, `ci/cd config` → ALWAYS ESCALATE

## Rate Limiting & Degradation

### API Rate Limits
- Free tier: 15 requests/minute
- Exponential backoff on 429 errors
- Graceful degradation under load

### Timeout Protection
- API calls: 300s max timeout
- Sandbox commands: 60s max timeout
- Overall incident: 15 minute hard limit

## Audit Trail

Every action is logged with:
- Timestamp
- Incident ID
- Component
- Action taken
- Reasoning trace

## Human Escalation

When confidence is below threshold, Nightingale:
1. Generates a detailed report
2. Explains what it tried
3. Shows verification failures
4. Provides recommended next steps

**Humans always have final say.**

## Never Autonomous

Nightingale will NEVER:
- Push code to production
- Create pull requests
- Merge changes
- Deploy applications
- Access production secrets
- Modify CI/CD pipelines

The agent **proposes** fixes. Humans **apply** them.
