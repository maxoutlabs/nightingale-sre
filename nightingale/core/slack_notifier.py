"""
Nightingale Slack Notifier
Posts incident resolution / escalation messages to a Slack webhook.
Silent no-op when SLACK_WEBHOOK_URL is not configured.
"""
import os
import json
from typing import Optional

import httpx

from nightingale.types import FixPlan, IncidentEvent, DecisionType
from nightingale.core.logger import logger
from nightingale.config import config


class SlackNotifier:
    """Sends formatted Slack messages via incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _post(self, payload: dict) -> bool:
        try:
            with httpx.Client(timeout=10) as client:
                r = client.post(
                    self.webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                r.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Slack notification failed: {e}", component="slack")
            return False

    def notify_resolved(
        self,
        event: IncidentEvent,
        plan: FixPlan,
        confidence: float,
        pr_url: Optional[str] = None,
    ) -> bool:
        """Post a 'resolved' notification."""
        files_changed = [d.file_path for d in plan.files_to_change]
        files_str = ", ".join(f"`{f}`" for f in files_changed) or "_none_"

        pr_section = f"\n🔗 <{pr_url}|View Pull Request>" if pr_url else ""

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Nightingale: CI Failure Auto-Resolved",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Incident:*\n`{event.id}`"},
                    {"type": "mrkdwn", "text": f"*Repository:*\n`{event.repository_path}`"},
                    {"type": "mrkdwn", "text": f"*Branch:*\n`{event.branch}`"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n`{confidence:.1%}`"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔍 Root Cause*\n{plan.root_cause or plan.rationale}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*🔧 Fix Applied*\n{plan.rationale}\n\n"
                        f"*Files:* {files_str}"
                        f"{pr_section}"
                    ),
                },
            },
            {"type": "divider"},
        ]

        return self._post({"blocks": blocks})

    def notify_escalated(
        self,
        event: IncidentEvent,
        plan: FixPlan,
        confidence: float,
        reason: str = "",
    ) -> bool:
        """Post an 'escalated' notification."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚠️ Nightingale: CI Failure Escalated to Human",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Incident:*\n`{event.id}`"},
                    {"type": "mrkdwn", "text": f"*Repository:*\n`{event.repository_path}`"},
                    {"type": "mrkdwn", "text": f"*Branch:*\n`{event.branch}`"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n`{confidence:.1%}` (below threshold)"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*🔍 Root Cause*\n{plan.root_cause or 'Unable to determine'}\n\n"
                        f"*Reason for escalation:* {reason or 'Confidence below auto-resolve threshold'}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "👤 *Action Required:* Please review and fix this incident manually.",
                },
            },
            {"type": "divider"},
        ]

        return self._post({"blocks": blocks})


def send_notification(
    event: IncidentEvent,
    plan: FixPlan,
    decision: str,
    confidence: float,
    pr_url: Optional[str] = None,
    reason: str = "",
) -> bool:
    """
    Send a Slack notification for an incident resolution or escalation.
    Returns True on success, False on error or if not configured.
    """
    webhook_url = (
        os.getenv("SLACK_WEBHOOK_URL", "")
        or config.get("slack.webhook_url", "")
    )

    if not webhook_url:
        return False  # Silent no-op

    notifier = SlackNotifier(webhook_url=webhook_url)

    if decision == "resolve":
        return notifier.notify_resolved(event, plan, confidence, pr_url=pr_url)
    else:
        return notifier.notify_escalated(event, plan, confidence, reason=reason)
