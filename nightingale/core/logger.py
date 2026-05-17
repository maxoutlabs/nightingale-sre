"""
Nightingale Logging System
Structured logging with timestamps, reasoning traces, and metrics
"""
import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

# Force UTF-8 on Windows so emoji in Rich output don't crash cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in ("incident_id", "attempt", "component", "duration_ms", "tokens"):
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        return json.dumps(log_data)


class NightingaleLogger:
    """Enhanced logger with structured output and rich console display."""

    def __init__(self, name: str = "nightingale", log_file: Optional[Path] = None):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            markup=True
        )
        rich_handler.setLevel(logging.INFO)
        self.logger.addHandler(rich_handler)

        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(StructuredFormatter())
            file_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(file_handler)

    def _log_with_context(self, level: int, msg: str, **kwargs):
        extra = {k: v for k, v in kwargs.items() if v is not None}
        self.logger.log(level, msg, extra=extra)

    def info(self, msg: str, **kwargs):
        self._log_with_context(logging.INFO, msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        self._log_with_context(logging.DEBUG, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._log_with_context(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._log_with_context(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        self._log_with_context(logging.CRITICAL, msg, **kwargs)

    # === Specialized Methods ===

    def incident_start(self, incident_id: str, incident_type: str, repo: str):
        console.print(Panel(
            f"[bold cyan]Incident ID:[/] {incident_id}\n"
            f"[bold cyan]Type:[/] {incident_type}\n"
            f"[bold cyan]Repository:[/] {repo}",
            title="[bold red]CI FAILURE DETECTED[/]",
            border_style="red"
        ))
        self.info(f"Processing incident {incident_id}",
                  incident_id=incident_id, component="orchestrator")

    def attempt_start(self, incident_id: str, attempt: int, max_attempts: int):
        console.print(f"\n[bold yellow]{'━' * 40} Attempt {attempt}/{max_attempts} {'━' * 40}[/]")
        self.info(f"Starting attempt {attempt}/{max_attempts}",
                  incident_id=incident_id, attempt=attempt, component="marathon")

    def reasoning_step(self, incident_id: str, attempt: int, step: str, details: str = ""):
        console.print(f"  [dim]├─[/] [cyan]{step}[/] {details}")
        self.debug(f"Reasoning: {step}",
                   incident_id=incident_id, attempt=attempt, component="reasoning")

    def api_call(self, incident_id: str, model: str, tokens: int, duration_ms: int):
        console.print(f"  [dim]├─[/] [magenta]API Call:[/] {model} ({tokens} tokens, {duration_ms}ms)")
        self.debug(f"API call to {model}",
                   incident_id=incident_id, tokens=tokens, duration_ms=duration_ms, component="gemini")

    def verification_result(self, incident_id: str, success: bool,
                            passed: int, failed: int, total: int):
        status = "[green]PASSED[/]" if success else "[red]FAILED[/]"
        console.print(f"  [dim]├─[/] [bold]Verification:[/] {status} ({passed}/{total} tests)")
        self.info(f"Verification {'passed' if success else 'failed'}: {passed}/{total}",
                  incident_id=incident_id, component="verifier")

    def confidence_breakdown(self, incident_id: str, score: float, factors: Dict[str, float]):
        """Print full confidence breakdown with weights and math."""
        table = Table(title="Confidence Breakdown", border_style="cyan")
        table.add_column("Factor", style="bold")
        table.add_column("Raw Score", justify="right")
        table.add_column("Weight", justify="right")
        table.add_column("Contribution", justify="right", style="green")

        weights = {
            "test_pass_ratio": 0.35,
            "inverse_blast_radius": 0.25,
            "attempt_penalty": 0.15,
            "risk_modifier": 0.15,
            "self_consistency_score": 0.10,
        }

        total = 0.0
        for name, weight in weights.items():
            raw = factors.get(name, 0.0)
            contribution = raw * weight
            total += contribution
            table.add_row(
                name.replace("_", " ").title(),
                f"{raw:.3f}",
                f"{weight:.0%}",
                f"{contribution:.4f}"
            )

        table.add_row("", "", "", "─" * 8)
        color = "green" if total >= 0.85 else "yellow" if total >= 0.6 else "red"
        table.add_row("[bold]TOTAL[/]", "", "", f"[bold {color}]{total:.4f} ({total:.1%})[/]")

        console.print(table)
        self.info(f"Confidence: {score:.2%}", incident_id=incident_id, component="scoring")

    # Backward compat alias
    def confidence_score(self, incident_id: str, score: float, factors: Dict[str, float]):
        self.confidence_breakdown(incident_id, score, factors)

    def decision(self, incident_id: str, decision: str, confidence: float):
        if decision == "resolve":
            console.print(Panel(
                f"[bold green]AUTO-RESOLVING[/]\nConfidence: {confidence:.2%}",
                title="Decision", border_style="green"
            ))
        else:
            console.print(Panel(
                f"[bold yellow]ESCALATING TO HUMAN[/]\nConfidence: {confidence:.2%}",
                title="Decision", border_style="yellow"
            ))
        self.info(f"Decision: {decision}", incident_id=incident_id, component="resolution")

    def show_fix_plan(self, rationale: str, files: list):
        console.print(f"\n  [bold]Fix Plan:[/]")
        console.print(f"  [dim]├─[/] [italic]{rationale}[/]")
        for f in files:
            console.print(f"  [dim]├─[/] {f.file_path} [{f.change_type}]")

    def show_code_diff(self, file_path: str, content: str, language: str = "python"):
        syntax = Syntax(content, language, theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title=f"{file_path}", border_style="blue"))

    def metrics_summary(self, metrics: Dict[str, Any]):
        table = Table(title="Performance Metrics", border_style="cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        for k, v in metrics.items():
            label = k.replace("_", " ").title()
            table.add_row(label, str(v))
        console.print(table)


# Global logger instance
logger = NightingaleLogger()
