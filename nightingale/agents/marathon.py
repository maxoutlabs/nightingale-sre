"""
Nightingale Marathon Agent
Multi-attempt reflective reasoning using GPT-4o.
"""
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

from nightingale.types import (
    IncidentEvent, FixPlan, FileDiff, RiskLevel,
    AIFixResponse, ReasoningTrace, AttemptRecord, VerificationResult,
)
from nightingale.core.context import RepositoryContextLoader
from nightingale.core.openai_client import get_openai_client, OpenAIClientError, QuotaExhaustedError
from nightingale.core.logger import logger
from nightingale.config import config

# Keep old import name for any code that does `from ... import GeminiClientError`
GeminiClientError = OpenAIClientError


class MarathonAgent:
    """
    Multi-attempt reflective reasoning agent using GPT-4o.

    Features:
    - Up to 3 fix attempts
    - Feeds verification failure logs back for root cause revision
    - Full reasoning trace
    - Structured outputs via OpenAI beta.chat.completions.parse()
    """

    MAX_ATTEMPTS = 3

    def __init__(self):
        self.client = get_openai_client()
        self.current_trace: Optional[ReasoningTrace] = None

    def analyze(
        self,
        event: IncidentEvent,
        context_loader: RepositoryContextLoader,
        attempt_number: int = 1,
        previous_failure: Optional[str] = None,
        previous_plan: Optional[FixPlan] = None,
    ) -> FixPlan:
        """
        Analyze a CI incident and generate a fix plan.

        Args:
            event: The incident to analyze
            context_loader: Repository context loader
            attempt_number: Current attempt (1-3)
            previous_failure: Logs from previous failed attempt
            previous_plan: The plan that failed (for reflection)

        Returns:
            FixPlan with proposed file changes
        """
        start_time = time.time()

        self.current_trace = ReasoningTrace(
            incident_id=event.id,
            attempt_number=attempt_number,
        )

        logger.attempt_start(event.id, attempt_number, self.MAX_ATTEMPTS)

        # Step 1: Gather context
        logger.reasoning_step(event.id, attempt_number, "Gathering repository context")
        context = self._gather_context(event, context_loader)

        # Step 2: Build prompt
        logger.reasoning_step(event.id, attempt_number, "Constructing analysis prompt")
        prompt = self._build_prompt(event, context, attempt_number, previous_failure, previous_plan)

        # Step 3: Call GPT-4o for structured response
        logger.reasoning_step(event.id, attempt_number, "Calling GPT-4o for analysis (structured output)")
        try:
            response: AIFixResponse = self.client.generate_structured(
                prompt=prompt,
                response_model=AIFixResponse,
                incident_id=event.id,
            )
        except OpenAIClientError as e:
            logger.error(f"OpenAI API failed: {e}", incident_id=event.id)
            raise

        # Step 4: Convert to FixPlan
        logger.reasoning_step(event.id, attempt_number, "Building fix plan from structured response")
        fix_plan = self._response_to_plan(response, event, attempt_number, previous_failure)

        logger.show_fix_plan(fix_plan.rationale, fix_plan.files_to_change)

        duration_ms = int((time.time() - start_time) * 1000)
        self.current_trace.total_duration_ms = duration_ms
        self.current_trace.completed_at = datetime.now()

        return fix_plan

    def _gather_context(
        self,
        event: IncidentEvent,
        context_loader: RepositoryContextLoader,
    ) -> Dict[str, Any]:
        """Gather relevant repository context for the prompt."""
        context: Dict[str, Any] = {
            "files": [],
            "recent_commits": [],
            "failed_file_content": None,
        }

        try:
            all_files = context_loader.list_files()
            context["files"] = [f for f in all_files if f.endswith(".py")][:20]
        except Exception as e:
            logger.warning(f"Could not list files: {e}")

        try:
            context["recent_commits"] = context_loader.get_recent_commits(3)
        except Exception as e:
            logger.warning(f"Could not get commits: {e}")

        # Find and load the content of the most likely failing file
        if event.failed_steps:
            logs = event.failed_steps[-1].logs or ""
            for f in context.get("files", []):
                if f in logs:
                    try:
                        content = context_loader.get_file_content(f)
                        context["failed_file_content"] = {"path": f, "content": content[:4000]}
                        break
                    except Exception:
                        pass

            # Also try reading directly from disk if git show fails
            if not context["failed_file_content"]:
                import os
                for f in context.get("files", []):
                    if f in logs:
                        full_path = os.path.join(context_loader.repo_path, f)
                        if os.path.exists(full_path):
                            try:
                                with open(full_path, encoding="utf-8") as fh:
                                    content = fh.read()
                                context["failed_file_content"] = {"path": f, "content": content[:4000]}
                                break
                            except Exception:
                                pass

        return context

    def _build_prompt(
        self,
        event: IncidentEvent,
        context: Dict[str, Any],
        attempt_number: int,
        previous_failure: Optional[str],
        previous_plan: Optional[FixPlan],
    ) -> str:
        """Build the analysis prompt for GPT-4o."""
        prompt = f"""You are an expert Site Reliability Engineer. Analyze the following CI/CD failure and provide a precise fix.

## Incident
- **ID**: {event.id}
- **Type**: {event.type.value}
- **Repository**: {event.repository_path}
- **Branch**: {event.branch}
- **Commit**: {event.commit_sha}

## CI Failure Logs
"""
        if event.failed_steps:
            step = event.failed_steps[-1]
            prompt += f"""```
{step.logs or 'No logs available'}
```
"""

        if context.get("files"):
            prompt += f"\n## Repository Files (Python)\n{', '.join(context['files'][:15])}\n"

        if context.get("failed_file_content"):
            fc = context["failed_file_content"]
            prompt += f"""
## Failing File: {fc['path']}
```python
{fc['content']}
```
"""

        if attempt_number > 1 and previous_failure and previous_plan:
            prompt += f"""
## ⚠️ REFLECTION REQUIRED — Previous Fix Failed (Attempt {attempt_number}/{self.MAX_ATTEMPTS})

**Previous rationale**: {previous_plan.rationale}
**Previous root cause**: {previous_plan.root_cause}

**Verification failure logs**:
```
{previous_failure[-2000:]}
```

You MUST:
1. Re-examine the root cause — your previous analysis was wrong
2. Propose a DIFFERENT approach
3. Read the failure logs carefully for the actual error
"""

        prompt += """
## Task
1. Identify the exact ROOT CAUSE of the CI failure
2. Propose the MINIMAL fix — change only what's necessary
3. Provide the complete new file content (not a diff) for each changed file
4. Be conservative and precise

Important: provide complete file contents for `content` field, not partial diffs."""

        return prompt

    def _response_to_plan(
        self,
        response: AIFixResponse,
        event: IncidentEvent,
        attempt_number: int,
        previous_failure: Optional[str],
    ) -> FixPlan:
        """Convert AIFixResponse to FixPlan."""
        files_to_change = [
            FileDiff(
                file_path=f.file_path,
                change_type=f.change_type,
                diff_content=f.content,
            )
            for f in response.files_to_change
        ]

        risk_map = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "critical": RiskLevel.CRITICAL,
        }
        risk = risk_map.get(response.risk_assessment.lower(), RiskLevel.MEDIUM)

        return FixPlan(
            rationale=response.rationale,
            root_cause=response.root_cause,
            files_to_change=files_to_change,
            verification_steps=response.verification_commands,
            confidence_score=response.confidence,
            risk_level=risk,
            attempt_number=attempt_number,
            previous_failure_context=previous_failure,
        )

    def get_trace(self) -> Optional[ReasoningTrace]:
        return self.current_trace


class ReflectiveReasoningLoop:
    """
    Orchestrates multi-attempt reasoning with reflection on failures.
    """

    def __init__(self, agent: MarathonAgent):
        self.agent = agent
        self.attempts: List[AttemptRecord] = []

    def run(
        self,
        event: IncidentEvent,
        context_loader: RepositoryContextLoader,
        verify_callback,
    ) -> tuple[Optional[FixPlan], List[AttemptRecord]]:
        """
        Run the reflective reasoning loop.

        Returns:
            (successful_plan, all_attempts) or (None, all_attempts) if all failed
        """
        previous_failure = None
        previous_plan = None

        for attempt_num in range(1, self.agent.MAX_ATTEMPTS + 1):
            record = AttemptRecord(
                attempt_number=attempt_num,
                started_at=datetime.now(),
            )

            try:
                plan = self.agent.analyze(
                    event=event,
                    context_loader=context_loader,
                    attempt_number=attempt_num,
                    previous_failure=previous_failure,
                    previous_plan=previous_plan,
                )
                record.fix_plan = plan
                record.reasoning_trace = self.agent.get_trace()

                result: VerificationResult = verify_callback(plan)
                record.verification_result = result
                record.completed_at = datetime.now()

                if result.success:
                    self.attempts.append(record)
                    return plan, self.attempts
                else:
                    previous_failure = result.output_log
                    previous_plan = plan
                    record.failure_reason = "Verification failed"

            except Exception as e:
                record.failure_reason = str(e)
                record.completed_at = datetime.now()
                previous_failure = str(e)

            self.attempts.append(record)

        return None, self.attempts
