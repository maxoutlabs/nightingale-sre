"""
Nightingale FastAPI Application
Webhook listener + Web Dashboard + REST API

Endpoints:
  GET  /                           Web dashboard
  GET  /api/v1/incidents           List incidents (JSON)
  GET  /api/v1/incidents/{id}      Incident detail (JSON)
  GET  /api/v1/metrics             Summary metrics (JSON)
  GET  /api/v1/config              Current config
  POST /api/v1/config/auto-resolve Toggle auto-resolve
  GET  /health                     Health check
  POST /webhook/github             GitHub webhook receiver
  POST /incident                   Direct incident submission
"""
import hmac
import hashlib
import asyncio
import json
import os
from typing import Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Header
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nightingale.types import IncidentEvent, IncidentType, PipelineStep
from nightingale.core.orchestrator import Orchestrator
from nightingale.core.database import get_db
from nightingale.core.logger import logger
from nightingale.config import config


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nightingale SRE",
    description="Autonomous CI/CD Repair Agent — Dashboard & Webhook API",
    version="1.0.0",
)

# Serve static files if the directory exists
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Models ────────────────────────────────────────────────────────────────────

class WebhookResponse(BaseModel):
    status: str
    message: str
    incident_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str


class AutoResolveRequest(BaseModel):
    enabled: bool


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the web dashboard."""
    html_path = _static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found. Run with static/ directory.</h1>", status_code=404)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/incidents")
async def list_incidents(limit: int = 50, offset: int = 0):
    """List all incidents, newest first."""
    db = get_db()
    incidents = db.get_dashboard_incidents(limit=limit)
    return {"incidents": [i.model_dump() for i in incidents], "total": len(incidents)}


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get full incident detail including report JSON."""
    db = get_db()
    row = db.get_incident(incident_id)
    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Parse the stored report JSON for rich detail
    try:
        report = json.loads(row.get("report_json", "{}"))
    except Exception:
        report = {}

    return {
        **row,
        "report": report,
    }


@app.get("/api/v1/metrics")
async def get_metrics():
    """Aggregated metrics for the dashboard header."""
    db = get_db()
    metrics = db.get_metrics()
    return metrics.model_dump()


@app.get("/api/v1/config")
async def get_config():
    """Get current configuration."""
    db = get_db()
    return {
        "auto_resolve_enabled": db.is_auto_resolve_enabled(),
        "resolve_threshold": config.get("confidence.resolve_threshold", 0.85),
        "model": config.get("openai.model", "gpt-4o"),
        "mini_model": config.get("openai.mini_model", "gpt-4o-mini"),
        "github_pr_enabled": bool(
            os.getenv("GITHUB_TOKEN") or config.get("github.token")
        ),
        "slack_enabled": bool(
            os.getenv("SLACK_WEBHOOK_URL") or config.get("slack.webhook_url")
        ),
    }


@app.post("/api/v1/config/auto-resolve")
async def set_auto_resolve(request: AutoResolveRequest):
    """Toggle the auto-resolve setting."""
    db = get_db()
    db.set_auto_resolve(request.enabled)
    state = "enabled" if request.enabled else "disabled"
    logger.info(f"Auto-resolve {state} via dashboard API", component="dashboard")
    return {"auto_resolve_enabled": request.enabled, "message": f"Auto-resolve {state}"}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
    )


# ── Webhook ───────────────────────────────────────────────────────────────────

def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return True
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_github_workflow_event(payload: dict) -> Optional[IncidentEvent]:
    workflow_run = payload.get("workflow_run", {})
    if workflow_run.get("conclusion") != "failure":
        return None
    repository = payload.get("repository", {})
    logs_url = workflow_run.get("logs_url", "")
    return IncidentEvent(
        id=f"gh-{workflow_run.get('id', 'unknown')}",
        type=IncidentType.PIPELINE_FAILURE,
        timestamp=datetime.now(),
        repository_path=repository.get("full_name", ""),
        commit_sha=workflow_run.get("head_sha", "HEAD"),
        branch=workflow_run.get("head_branch", "main"),
        failed_steps=[PipelineStep(
            name=workflow_run.get("name", "unknown"),
            status="failure",
            logs=f"Workflow failed. Logs: {logs_url}",
        )],
        metadata={
            "source": "github_webhook",
            "workflow_name": workflow_run.get("name"),
            "run_number": workflow_run.get("run_number"),
            "actor": workflow_run.get("actor", {}).get("login"),
            "logs_url": logs_url,
        },
        workflow_file=workflow_run.get("path"),
    )


def parse_github_check_run_event(payload: dict) -> Optional[IncidentEvent]:
    check_run = payload.get("check_run", {})
    if check_run.get("conclusion") not in ("failure", "timed_out"):
        return None
    repository = payload.get("repository", {})
    return IncidentEvent(
        id=f"gh-check-{check_run.get('id', 'unknown')}",
        type=IncidentType.TEST_FAILURE,
        timestamp=datetime.now(),
        repository_path=repository.get("full_name", ""),
        commit_sha=check_run.get("head_sha", "HEAD"),
        branch=check_run.get("check_suite", {}).get("head_branch", "main"),
        failed_steps=[PipelineStep(
            name=check_run.get("name", "unknown"),
            status="failure",
            logs=check_run.get("output", {}).get("text", "Check run failed"),
        )],
        metadata={"source": "github_webhook", "check_name": check_run.get("name")},
    )


async def process_incident_async(event: IncidentEvent):
    try:
        orchestrator = Orchestrator()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, orchestrator.process_incident, event)
    except Exception as e:
        logger.error(f"Background incident processing failed: {e}", incident_id=event.id)


@app.post("/webhook/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
):
    body = await request.body()
    webhook_secret = config.get("webhook.secret", "")
    if webhook_secret:
        if not verify_github_signature(body, x_hub_signature_256 or "", webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event: Optional[IncidentEvent] = None
    if x_github_event == "workflow_run":
        event = parse_github_workflow_event(payload)
    elif x_github_event == "check_run":
        event = parse_github_check_run_event(payload)
    elif x_github_event == "ping":
        return WebhookResponse(status="ok", message="Pong! Webhook configured correctly.")
    else:
        return WebhookResponse(status="ignored", message=f"Event '{x_github_event}' not handled")

    if not event:
        return WebhookResponse(status="ignored", message="Not a failure event, skipping")

    logger.info(f"Received GitHub incident: {event.id}", incident_id=event.id)
    background_tasks.add_task(process_incident_async, event)
    return WebhookResponse(status="accepted", message="Incident queued", incident_id=event.id)


@app.post("/incident", response_model=WebhookResponse)
async def submit_incident(incident: IncidentEvent, background_tasks: BackgroundTasks):
    """Direct incident submission endpoint."""
    logger.info(f"Received direct incident: {incident.id}", incident_id=incident.id)
    background_tasks.add_task(process_incident_async, incident)
    return WebhookResponse(status="accepted", message="Incident queued", incident_id=incident.id)


def run_webhook_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    print(f"\nNightingale Dashboard: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_webhook_server()
