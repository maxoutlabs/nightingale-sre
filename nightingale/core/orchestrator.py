"""
Nightingale Orchestrator
Central pipeline controller: context → reason → verify → score → decide → report.

New in v1.0:
- SQLite incident tracking with live status updates
- GitHub PR creation on auto-resolve (falls back to direct write)
- Slack notifications on resolve/escalate
- gpt-4o-mini risk classification in confidence scoring
"""
import uuid
import time
import os
from datetime import datetime
from typing import Optional, Callable

from nightingale.types import (
    IncidentEvent, FixPlan, VerificationResult, MetricsData,
    ConfidenceFactors, AttemptRecord, IncidentReport, DecisionType,
    IncidentStatus,
)
from nightingale.core.context import RepositoryContextLoader
from nightingale.core.sandbox import Sandbox
from nightingale.core.workflow_parser import WorkflowParser
from nightingale.core.logger import logger
from nightingale.core.openai_client import get_openai_client, QuotaExhaustedError
from nightingale.core.database import get_db
from nightingale.core.github_pr import create_fix_pr
from nightingale.core.slack_notifier import send_notification
from nightingale.agents.marathon import MarathonAgent, ReflectiveReasoningLoop
from nightingale.agents.verifier import VerificationAgent
from nightingale.analysis.confidence import ConfidenceScorer, ResolutionEngine
from nightingale.analysis.reporter import EscalationReporter
from nightingale.config import config


class Orchestrator:
    """
    Main pipeline orchestrator.

    Pipeline:
    1. Register incident in DB (status: detected)
    2. Load repository context
    3. Parse workflow test commands
    4. Reflective reasoning loop (up to 3 GPT-4o attempts)
    5. Confidence scoring (weighted 5-factor formula + gpt-4o-mini risk)
    6. Decision: auto-resolve or escalate
    7. If resolve: GitHub PR (or direct file write as fallback)
    8. Slack notification
    9. Save final incident record to DB
    10. Generate and return full incident report
    """

    def __init__(self, status_callback: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            status_callback: Optional callable(incident_id, status) for external status updates.
        """
        record_mode = os.getenv("NIGHTINGALE_RECORD_MODE") == "1"
        get_openai_client(record_mode=record_mode)

        self.marathon = MarathonAgent()
        self.verifier = VerificationAgent()
        self.scorer = ConfidenceScorer()
        self.resolver = ResolutionEngine(
            resolve_threshold=config.get("confidence.resolve_threshold", 0.85)
        )
        self.reporter = EscalationReporter()
        self.db = get_db()
        self.metrics: Optional[MetricsData] = None
        self.status_callback = status_callback

    def _update_status(self, incident_id: str, status: IncidentStatus):
        """Update incident status in DB and invoke callback."""
        self.db.update_status(incident_id, status.value)
        if self.status_callback:
            try:
                self.status_callback(incident_id, status.value)
            except Exception:
                pass

    def process_incident(self, event: IncidentEvent) -> IncidentReport:
        """Process a CI incident through the full pipeline."""
        start_time = time.time()

        self.metrics = MetricsData(
            incident_id=event.id,
            started_at=datetime.now(),
        )

        logger.incident_start(event.id, event.type.value, event.repository_path)

        # ── 0. Register in DB ──────────────────────────────────────────────────
        self.db.upsert_incident(
            incident_id=event.id,
            repo=event.repository_path,
            failure_type=event.type.value,
            status=IncidentStatus.DETECTED.value,
        )
        self._update_status(event.id, IncidentStatus.DETECTED)

        # ── 1. Load Context ────────────────────────────────────────────────────
        logger.info("Loading repository context...", incident_id=event.id, component="orchestrator")
        context_loader = RepositoryContextLoader(event.repository_path)

        try:
            all_files = context_loader.list_files()
            self.scorer = ConfidenceScorer(len(all_files))
        except Exception:
            pass

        # ── 2. Parse Workflows ─────────────────────────────────────────────────
        logger.info("Parsing workflows...", incident_id=event.id, component="orchestrator")
        workflow_parser = WorkflowParser(event.repository_path)

        # Allow scenario metadata to override workflow-derived commands
        test_commands = (
            event.metadata.get("test_commands")
            or workflow_parser.get_test_commands()
        )
        logger.info(f"Test commands: {test_commands}", incident_id=event.id, component="workflow")

        # ── 3. Reflective Reasoning Loop ───────────────────────────────────────
        self._update_status(event.id, IncidentStatus.DIAGNOSING)
        reasoning_loop = ReflectiveReasoningLoop(self.marathon)

        sandbox_id = f"sandbox_{event.id}_{uuid.uuid4().hex[:8]}"
        sandbox = Sandbox(event.repository_path, sandbox_id)

        final_plan: Optional[FixPlan] = None
        final_result: Optional[VerificationResult] = None
        attempts: list[AttemptRecord] = []

        def verify_callback(plan: FixPlan) -> VerificationResult:
            self.metrics.sandbox_runs += 1
            sandbox.setup()

            if test_commands:
                plan.verification_steps = test_commands

            sandbox.apply_diffs(plan.files_to_change)
            self.metrics.files_modified = len(plan.files_to_change)

            # Update status: fix generated, now sandboxing
            self._update_status(event.id, IncidentStatus.FIX_GENERATED)
            self._update_status(event.id, IncidentStatus.SANDBOXING)

            result = self.verifier.verify(sandbox, plan)
            logger.info(
                f"Verification: {'PASSED' if result.success else 'FAILED'} in {result.duration_ms}ms",
                incident_id=event.id, component="verifier"
            )
            return result

        try:
            final_plan, attempts = reasoning_loop.run(event, context_loader, verify_callback)

            if final_plan and attempts:
                final_result = attempts[-1].verification_result

            self.metrics.total_attempts = len(attempts)

        except QuotaExhaustedError as e:
            logger.error(f"API quota exhausted — escalating: {e}", incident_id=event.id)
            attempts = reasoning_loop.attempts or []
            self.metrics.total_attempts = len(attempts)

        except Exception as e:
            logger.error(f"Reasoning loop error — escalating: {e}", incident_id=event.id)
            attempts = reasoning_loop.attempts or []
            self.metrics.total_attempts = len(attempts)

        finally:
            if config.get("cleanup_sandbox", True):
                sandbox.cleanup()

        # Collect API metrics
        try:
            client_metrics = get_openai_client().get_metrics()
            self.metrics.total_api_calls = client_metrics["total_calls"]
            self.metrics.total_tokens_used = client_metrics["total_tokens"]
        except Exception:
            pass

        # ── 4. Confidence Scoring ──────────────────────────────────────────────
        if final_plan and final_result:
            # Use gpt-4o-mini to refine risk assessment
            try:
                ai_risk = get_openai_client().classify_risk(
                    files_changed=[d.file_path for d in final_plan.files_to_change],
                    context=final_plan.root_cause[:200],
                )
                # Override the AI's self-reported risk with gpt-4o-mini classification
                from nightingale.types import RiskLevel
                risk_map = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM,
                            "high": RiskLevel.HIGH, "critical": RiskLevel.CRITICAL}
                final_plan.risk_level = risk_map.get(ai_risk, final_plan.risk_level)
                logger.info(f"gpt-4o-mini risk classification: {ai_risk}", component="scoring")
            except Exception:
                pass

            confidence, factors = self.scorer.calculate(
                final_plan, final_result, final_plan.attempt_number
            )
        else:
            confidence = 0.0
            factors = ConfidenceFactors()

        logger.confidence_score(event.id, confidence, factors.model_dump())

        # ── 5. Decision ────────────────────────────────────────────────────────
        # Respect the DB auto-resolve toggle
        auto_resolve_enabled = self.db.is_auto_resolve_enabled()
        if not auto_resolve_enabled:
            decision = "escalate"
            logger.info("Auto-resolve disabled via dashboard — escalating.", incident_id=event.id)
        else:
            decision = self.resolver.decide(confidence, factors)

        logger.decision(event.id, decision, confidence)

        # ── 6. Apply Fix ───────────────────────────────────────────────────────
        pr_url: Optional[str] = None

        if decision == "resolve" and final_plan:
            # Try GitHub PR first
            pr_url = create_fix_pr(
                incident_id=event.id,
                plan=final_plan,
                confidence=confidence,
                factors=factors,
            )

            if pr_url:
                logger.info(f"Fix committed as GitHub PR: {pr_url}", incident_id=event.id, component="github")
            else:
                # Fallback: direct file write
                logger.info("Applying fix directly to repository (no GitHub token configured).",
                            incident_id=event.id, component="orchestrator")
                try:
                    self._apply_fix_to_repo(event.repository_path, final_plan)
                    logger.info("Fix applied to repository successfully.", incident_id=event.id)
                except Exception as e:
                    logger.error(f"Failed to apply fix: {e}", incident_id=event.id)

        # ── 7. Notifications ───────────────────────────────────────────────────
        if final_plan:
            try:
                sent = send_notification(
                    event=event,
                    plan=final_plan,
                    decision=decision,
                    confidence=confidence,
                    pr_url=pr_url,
                    reason=self.resolver.explain_decision(decision, confidence, factors) if decision == "escalate" else "",
                )
                if sent:
                    logger.info("Slack notification sent.", component="slack")
            except Exception as e:
                logger.warning(f"Slack notification failed: {e}", component="slack")

        # ── 8. Report ──────────────────────────────────────────────────────────
        self.metrics.total_duration_ms = int((time.time() - start_time) * 1000)
        self.metrics.completed_at = datetime.now()
        self.metrics.final_decision = DecisionType.RESOLVE if decision == "resolve" else DecisionType.ESCALATE
        self.metrics.final_confidence = confidence

        if final_plan and final_result:
            report = self.reporter.generate_report(
                event=event, plan=final_plan, result=final_result,
                confidence=confidence, factors=factors, decision=decision,
                attempts=attempts, metrics=self.metrics,
            )
        else:
            empty_plan = FixPlan(
                rationale="All fix attempts failed or API quota exhausted",
                root_cause="Unable to determine — escalated to human",
                files_to_change=[], verification_steps=[],
                confidence_score=0.0,
            )
            empty_result = VerificationResult(
                success=False, input_hash="",
                output_log="Escalated due to exhausted attempts or API quota", duration_ms=0,
            )
            report = self.reporter.generate_report(
                event=event, plan=empty_plan, result=empty_result,
                confidence=0.0, factors=ConfidenceFactors(), decision="escalate",
                attempts=attempts, metrics=self.metrics,
            )

        report.pr_url = pr_url
        report.status = IncidentStatus.RESOLVED if decision == "resolve" else IncidentStatus.ESCALATED

        # ── 9. Persist to DB ───────────────────────────────────────────────────
        final_status = IncidentStatus.RESOLVED if decision == "resolve" else IncidentStatus.ESCALATED
        fix_plan_for_db = final_plan or report.final_plan
        self.db.upsert_incident(
            incident_id=event.id,
            repo=event.repository_path,
            failure_type=event.type.value,
            status=final_status.value,
            attempts=self.metrics.total_attempts,
            confidence_score=confidence,
            outcome=decision,
            time_to_resolution_ms=self.metrics.total_duration_ms,
            root_cause=(fix_plan_for_db.root_cause or fix_plan_for_db.rationale) if fix_plan_for_db else "",
            fix_summary=(fix_plan_for_db.rationale[:300]) if fix_plan_for_db else "",
            pr_url=pr_url or "",
            report_json=report.model_dump_json() if report else "{}",
        )
        self._update_status(event.id, final_status)

        # ── 10. Display metrics ────────────────────────────────────────────────
        logger.metrics_summary({
            "attempts": self.metrics.total_attempts,
            "api_calls": self.metrics.total_api_calls,
            "tokens_used": self.metrics.total_tokens_used,
            "duration_ms": self.metrics.total_duration_ms,
            "files_modified": self.metrics.files_modified,
            "sandbox_runs": self.metrics.sandbox_runs,
        })

        print("\n" + report.report_text)
        return report

    def _apply_fix_to_repo(self, repo_path: str, plan: FixPlan):
        """Fallback: apply the fix directly to the local repository."""
        for diff in plan.files_to_change:
            file_path = os.path.join(repo_path, diff.file_path)

            if diff.change_type in ("modify", "add"):
                os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else ".", exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(diff.diff_content)
            elif diff.change_type == "delete":
                if os.path.exists(file_path):
                    os.remove(file_path)
