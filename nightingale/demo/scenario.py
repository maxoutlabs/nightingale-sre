"""
Nightingale Demo Scenarios
Three CI failure scenarios that Nightingale can autonomously repair.

Scenarios:
  1. Test assertion bug  — wrong expected value in test assertion
  2. Broken import       — non-existent name imported from stdlib
  3. Logic bug           — off-by-one / wrong return value in algorithm
"""
import os
import time
from datetime import datetime
from typing import Optional

from nightingale.types import IncidentEvent, IncidentType, PipelineStep
from nightingale.core.orchestrator import Orchestrator
from nightingale.core.logger import logger, console
from nightingale.config import config

# ── Scenario definitions ──────────────────────────────────────────────────────

# Broken file content for each scenario (used to reset before a demo run)
BROKEN_CONTENT = {
    "demo_repo/test_app.py": """\
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def test_add():
    assert add(2, 2) == 4

def test_subtract():
    # This test is intentionally broken
    assert subtract(2, 2) == 1
""",
    "demo_repo/test_formatter.py": """\
# Scenario 2: Broken Import
# Bug: 'DefaultDict' does not exist in collections (correct name is 'defaultdict')

from collections import OrderedDict, DefaultDict  # ImportError: cannot import name 'DefaultDict'


def group_by_first_char(items):
    \"\"\"Group strings by their first character.\"\"\"
    result = DefaultDict(list)
    for item in items:
        if item:
            result[item[0].lower()].append(item)
    return dict(result)


def test_group_empty():
    assert group_by_first_char([]) == {}


def test_group_basic():
    result = group_by_first_char(["apple", "avocado", "banana"])
    assert "a" in result
    assert len(result["a"]) == 2
    assert "b" in result
    assert result["b"] == ["banana"]


def test_group_case_insensitive():
    result = group_by_first_char(["Apple", "avocado"])
    assert "a" in result
    assert len(result["a"]) == 2
""",
    "demo_repo/test_fibonacci.py": """\
# Scenario 3: Logic Bug
# Bug: fibonacci() returns 'a' instead of 'b' at the end of the loop.

def fibonacci(n):
    \"\"\"Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1, fib(2)=1, ...).\"\"\"
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a  # BUG: should be `return b`


def test_fibonacci_base_cases():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_fibonacci_small():
    # fib sequence: 0,1,1,2,3,5,8,13,21,34,55
    assert fibonacci(2) == 1   # passes (a=1 after 1 loop iter, but b=1 too)
    assert fibonacci(3) == 2   # FAILS: returns a=1, expected b=2
    assert fibonacci(4) == 3   # FAILS: returns a=2, expected b=3


def test_fibonacci_large():
    assert fibonacci(5) == 5    # FAILS: returns 3, expected 5
    assert fibonacci(10) == 55  # FAILS: returns 34, expected 55
""",
}


def restore_demo_files(scenario_id: Optional[str] = None):
    """
    Restore broken demo files so the demo can be re-run.
    Call before running a scenario to ensure files are in the broken state.
    """
    import os
    files_to_restore = {}
    if scenario_id:
        sc = SCENARIOS.get(scenario_id, {})
        f = sc.get("file")
        if f and f in BROKEN_CONTENT:
            files_to_restore[f] = BROKEN_CONTENT[f]
    else:
        files_to_restore = BROKEN_CONTENT

    for path, content in files_to_restore.items():
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except Exception as e:
            console.print(f"[yellow]Warning: could not restore {path}: {e}[/yellow]")


SCENARIOS = {
    "1": {
        "name": "Test Assertion Bug",
        "description": "A test has the wrong expected value -- assert subtract(2,2)==1 should be ==0.",
        "emoji": "[1]",
        "file": "demo_repo/test_app.py",
        "incident_type": IncidentType.TEST_FAILURE,
        "logs": """\
============================= test session starts ==============================
platform linux -- Python 3.10.0, pytest-7.4.0
collected 2 items

demo_repo/test_app.py .F                                                  [100%]

=================================== FAILURES ===================================
________________________________ test_subtract _________________________________

    def test_subtract():
        # This test is intentionally broken
>       assert subtract(2, 2) == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = subtract(2, 2)

demo_repo/test_app.py:12: AssertionError
=========================== short test summary info ============================
FAILED demo_repo/test_app.py::test_subtract - AssertionError: assert 0 == 1
========================= 1 failed, 1 passed in 0.12s =========================
""",
        "test_commands": ["python -m pytest demo_repo/test_app.py -v"],
    },

    "2": {
        "name": "Broken Import",
        "description": "'DefaultDict' doesn't exist in collections (should be 'defaultdict').",
        "emoji": "[2]",
        "file": "demo_repo/test_formatter.py",
        "incident_type": IncidentType.BUILD_FAILURE,
        "logs": """\
============================= test session starts ==============================
platform linux -- Python 3.10.0, pytest-7.4.0
collecting ...

ERROR collecting demo_repo/test_formatter.py
ImportError while importing test module 'demo_repo/test_formatter.py'.

Traceback (most recent call last):
  File "demo_repo/test_formatter.py", line 4, in <module>
    from collections import OrderedDict, DefaultDict
ImportError: cannot import name 'DefaultDict' from 'collections'

=========================== short test summary info ============================
ERROR demo_repo/test_formatter.py -- ImportError: cannot import name 'DefaultDict' from 'collections'
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
============================================================= no tests ran =====
""",
        "test_commands": ["python -m pytest demo_repo/test_formatter.py -v"],
    },

    "3": {
        "name": "Logic Bug",
        "description": "fibonacci() returns `a` instead of `b` -- every result for n>=3 is wrong.",
        "emoji": "[3]",
        "file": "demo_repo/test_fibonacci.py",
        "incident_type": IncidentType.TEST_FAILURE,
        "logs": """\
============================= test session starts ==============================
platform linux -- Python 3.10.0, pytest-7.4.0
collected 3 items

demo_repo/test_fibonacci.py .FF                                           [100%]

=================================== FAILURES ===================================
______________________________ test_fibonacci_small ____________________________

    def test_fibonacci_small():
>       assert fibonacci(3) == 2
E       AssertionError: assert 1 == 2

demo_repo/test_fibonacci.py:21: AssertionError
________________________ test_fibonacci_large ____________________________

    def test_fibonacci_large():
>       assert fibonacci(5) == 5
E       AssertionError: assert 3 == 5

demo_repo/test_fibonacci.py:26: AssertionError
=========================== short test summary info ============================
FAILED demo_repo/test_fibonacci.py::test_fibonacci_small - AssertionError: assert 1 == 2
FAILED demo_repo/test_fibonacci.py::test_fibonacci_large - AssertionError: assert 3 == 5
========================= 2 failed, 1 passed in 0.08s ==========================
""",
        "test_commands": ["python -m pytest demo_repo/test_fibonacci.py -v"],
    },
}


# ── Scenario runner ───────────────────────────────────────────────────────────

def _make_incident(scenario_id: str, repo_path: str) -> IncidentEvent:
    sc = SCENARIOS[scenario_id]
    return IncidentEvent(
        id=f"demo-{scenario_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        type=sc["incident_type"],
        timestamp=datetime.now(),
        repository_path=repo_path,
        commit_sha="HEAD",
        branch="main",
        failed_steps=[
            PipelineStep(
                name="pytest",
                status="failure",
                logs=sc["logs"],
                duration_ms=120,
            )
        ],
        metadata={
            "trigger": "demo",
            "scenario": scenario_id,
            "test_commands": sc["test_commands"],
        },
    )


def _run_scenario(scenario_id: str, repo_path: str, record_mode: bool = False) -> object:
    sc = SCENARIOS[scenario_id]

    # Restore broken file state so demo is repeatable
    restore_demo_files(scenario_id)

    console.print(f"\n[bold]{sc['emoji']} Scenario {scenario_id}: {sc['name']}[/bold]")
    console.print(f"  [dim]{sc['description']}[/dim]")
    console.print(f"  [dim]Target file: {sc['file']}[/dim]\n")

    incident = _make_incident(scenario_id, repo_path)

    console.print("[bold red]CI FAILURE DETECTED[/bold red]")
    console.print("[dim]Dispatching Nightingale Agent…[/dim]\n")
    time.sleep(0.3)

    orchestrator = Orchestrator()
    report = orchestrator.process_incident(incident)

    if report.decision.value == "resolve":
        console.print(f"\n[bold green]RESOLVED: Scenario {scenario_id} resolved autonomously.[/bold green]")
        if report.pr_url:
            console.print(f"[green]Pull Request: {report.pr_url}[/green]")
    else:
        console.print(f"\n[bold yellow]ESCALATED: Scenario {scenario_id} escalated to human review.[/bold yellow]")

    return report


def _scenario_picker() -> list[str]:
    """Display a pretty menu and return a list of scenario IDs to run."""
    console.print("""
[bold cyan]
  NIGHTINGALE SRE
  Autonomous CI/CD Repair Agent
[/bold cyan]
  [bold white]Powered by GPT-4o + GPT-4o-mini[/bold white]
""")

    from rich.table import Table
    t = Table(show_header=True, header_style="bold cyan", border_style="dim")
    t.add_column("#", style="bold", width=3)
    t.add_column("Scenario", style="bold white")
    t.add_column("Description", style="dim")
    t.add_column("Bug Type", style="yellow")

    bug_types = {"1": "Wrong assertion", "2": "ImportError", "3": "Wrong return value"}
    for sid, sc in SCENARIOS.items():
        t.add_row(sid, sc['name'], sc["description"], bug_types[sid])

    t.add_row("A", "All Scenarios", "Run all three scenarios in sequence", "-")
    console.print(t)
    console.print()

    choice = input("  Select scenario [1/2/3/A, default=A]: ").strip().upper() or "A"

    if choice == "A":
        return ["1", "2", "3"]
    elif choice in SCENARIOS:
        return [choice]
    else:
        console.print(f"[yellow]Unknown choice '{choice}', running all scenarios.[/yellow]")
        return ["1", "2", "3"]


# ── Public API ────────────────────────────────────────────────────────────────

def run_demo(record_mode: bool = False, scenario_id: Optional[str] = None):
    """
    Run one or all demo scenarios.

    Args:
        record_mode: Replay cached API responses (no live API calls)
        scenario_id: Specific scenario to run (1/2/3), or None to show picker
    """
    repo_path = os.path.abspath(config.get("demo.repo_path", "."))
    console.print(f"[dim]Repository: {repo_path}[/dim]")

    if record_mode:
        console.print("[bold yellow][record-mode] Replaying cached API responses[/bold yellow]")

    if scenario_id:
        # Direct run, no picker
        scenarios_to_run = [scenario_id] if scenario_id in SCENARIOS else ["1"]
    else:
        scenarios_to_run = _scenario_picker()

    reports = []
    for sid in scenarios_to_run:
        try:
            report = _run_scenario(sid, repo_path, record_mode)
            reports.append(report)
        except Exception as e:
            console.print(f"[bold red]Scenario {sid} failed with error: {e}[/bold red]")
            if len(scenarios_to_run) == 1:
                raise

        if len(scenarios_to_run) > 1 and sid != scenarios_to_run[-1]:
            console.print("\n[dim]─────────────────────────────────────────[/dim]")
            time.sleep(1)

    # Summary if multiple
    if len(reports) > 1:
        resolved = sum(1 for r in reports if r.decision.value == "resolve")
        console.print(f"\n[bold cyan]Demo Complete: {resolved}/{len(reports)} scenarios auto-resolved[/bold cyan]")

    return reports if len(reports) > 1 else (reports[0] if reports else None)


if __name__ == "__main__":
    run_demo()
