# Nightingale Telemetry & Metrics

## Overview

Nightingale collects comprehensive telemetry data to enable observability, debugging, and performance optimization of the autonomous CI repair agent.

## Metrics Collected

### Incident Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `incident_id` | string | Unique incident identifier |
| `incident_type` | enum | Type of CI failure (test, build, lint, pipeline) |
| `total_attempts` | counter | Number of fix attempts made (1-3) |
| `final_decision` | enum | RESOLVE or ESCALATE |
| `final_confidence` | float | Final confidence score [0.0-1.0] |

### API Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `total_api_calls` | counter | Total Gemini API calls made |
| `total_tokens_used` | counter | Total tokens consumed |
| `requests_per_minute` | gauge | Current RPM against rate limit |

### Performance Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `total_duration_ms` | timer | End-to-end processing time |
| `api_call_duration_ms` | timer | Per-call API latency |
| `sandbox_runs` | counter | Number of sandbox executions |

### Confidence Factors
| Factor | Weight | Description |
|--------|--------|-------------|
| `test_pass_ratio` | 35% | Percentage of tests passing |
| `inverse_blast_radius` | 25% | 1 - (files_changed / total_files) |
| `attempt_penalty` | 15% | 1.0 for attempt 1, 0.7 for 2, 0.4 for 3 |
| `risk_modifier` | 15% | Based on file criticality |
| `self_consistency_score` | 10% | Model's self-assessed confidence |

## Logging

### Structured JSON Logs
Logs are written in JSON format for easy parsing:

```json
{
  "timestamp": "2026-02-09T14:30:00.123Z",
  "level": "INFO",
  "logger": "nightingale",
  "message": "Processing incident demo-001",
  "incident_id": "demo-001",
  "component": "orchestrator"
}
```

### Log Levels
- **DEBUG**: Detailed reasoning traces, API payloads
- **INFO**: Pipeline progress, decisions, metrics
- **WARNING**: Rate limits, retries, degraded performance
- **ERROR**: API failures, validation errors

## Reasoning Traces

Each fix attempt captures a complete reasoning trace:

```python
ReasoningTrace(
    incident_id="demo-001",
    attempt_number=1,
    steps=[
        ReasoningStep(action="gather_context", ...),
        ReasoningStep(action="analyze_failure", ...),
        ReasoningStep(action="generate_fix", ...)
    ],
    total_tokens=1523,
    total_duration_ms=4500
)
```

## Data Retention

- Logs: Stored in `nightingale.log` (configurable)
- Reports: Generated per-incident as IncidentReport objects
- Metrics: In-memory during execution, logged on completion

## Integration Points

### Prometheus (Future)
Metrics can be exposed via `/metrics` endpoint for Prometheus scraping.

### External Logging
Configure external log shipping via standard logging handlers.
