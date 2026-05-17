"""
Nightingale v1.0 - Autonomous CI SRE Agent
Entry point for all CLI commands.
"""
import sys
import os
import shutil
import argparse
import importlib

# Force UTF-8 stdout/stderr on Windows so emoji in library output don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def require_api_key():
    """Check OPENAI_API_KEY is set. Print clear error and exit if not."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        print("""
ERROR: OPENAI_API_KEY not set.

Set it using:

  PowerShell:
    $env:OPENAI_API_KEY = 'sk-...'

  Linux/macOS:
    export OPENAI_API_KEY='sk-...'
""")
        sys.exit(1)
    return key


def cmd_verify_api():
    """Verify the OpenAI API key with one minimal request."""
    require_api_key()
    from nightingale.core.openai_client import verify_api_key
    print("Verifying OpenAI API key...")
    result = verify_api_key()
    print()

    if result["reachable"]:
        print(f"  API reachable:  YES")
        print(f"  SDK:            {result.get('sdk', 'unknown')}")
        print(f"  Model:          {result['model']}")
        print(f"  Latency:        {result['latency_ms']}ms")
        print(f"  Tokens used:    {result['tokens']}")
        print(f"  Response:       \"{result['response']}\"")
        print()
        print("API key is valid and working.")
        return True

    if result.get("quota_exhausted"):
        print(f"  API reachable:  YES (key valid)")
        print(f"  Status:         QUOTA EXHAUSTED")
        print()
        print("API key is VALID but quota is exhausted. Wait or upgrade plan.")
        return True

    print(f"  API reachable:  NO")
    print(f"  Error:          {result['error']}")
    print()
    print("API key verification FAILED. Check your key.")
    sys.exit(1)


def cmd_self_check():
    """Run 9-point system diagnostic."""
    print("Running Nightingale self-check...\n")
    results = []

    # 1. API key present
    key = os.getenv("OPENAI_API_KEY", "")
    results.append(("API key present", bool(key), "$env:OPENAI_API_KEY = 'sk-...'"))

    # 2. API responds
    api_ok = False
    api_note = "Check your API key and internet connection"
    if key:
        from nightingale.core.openai_client import verify_api_key
        r = verify_api_key()
        api_ok = r["reachable"] or r.get("quota_exhausted", False)
        if r.get("quota_exhausted"):
            api_note = "Key valid but quota exhausted"
    results.append(("API responds", api_ok, api_note))

    # 3. Demo repo exists
    from nightingale.config import config
    demo_path = os.path.abspath(config.get("demo.repo_path", "."))
    results.append(("Demo repo exists", os.path.isdir(demo_path), f"Create: {demo_path}"))

    # 4. Demo scenario files exist
    scenario_files = [
        "demo_repo/test_app.py",
        "demo_repo/test_formatter.py",
        "demo_repo/test_fibonacci.py",
    ]
    all_exist = all(os.path.exists(f) for f in scenario_files)
    results.append(("Demo scenario files exist", all_exist,
                    "Missing: " + ", ".join(f for f in scenario_files if not os.path.exists(f))))

    # 5. Sandbox writable
    sandbox_dir = os.path.join(demo_path, config.get("sandbox_dir", ".sandbox"))
    try:
        os.makedirs(sandbox_dir, exist_ok=True)
        test_file = os.path.join(sandbox_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        sandbox_ok = True
    except Exception:
        sandbox_ok = False
    results.append(("Sandbox dir writable", sandbox_ok, f"Check permissions: {sandbox_dir}"))

    # 6. SQLite DB writable
    db_path = config.get("dashboard.db_path", "nightingale.db")
    try:
        from nightingale.core.database import IncidentDatabase
        IncidentDatabase(db_path)
        db_ok = True
    except Exception:
        db_ok = False
    results.append(("SQLite DB accessible", db_ok, f"Check path: {db_path}"))

    # 7. Dependencies installed
    deps_ok = True
    missing = []
    for mod in ["openai", "pydantic", "fastapi", "uvicorn", "rich", "yaml", "git", "httpx"]:
        try:
            importlib.import_module(mod)
        except ImportError:
            deps_ok = False
            missing.append(mod)
    results.append(("Dependencies installed", deps_ok,
                    f"pip install: {', '.join(missing)}" if missing else ""))

    # 8. Reflective loop max attempts > 1
    from nightingale.agents.marathon import MarathonAgent
    results.append(("Reflective loop attempts > 1", MarathonAgent.MAX_ATTEMPTS > 1,
                    "MarathonAgent.MAX_ATTEMPTS must be > 1"))

    # 9. Confidence weights sum to 1.0
    from nightingale.analysis.confidence import ConfidenceScorer
    weight_sum = sum(ConfidenceScorer.WEIGHTS.values())
    results.append(("Confidence weights sum to 1.0", abs(weight_sum - 1.0) < 0.001,
                    f"Current sum: {weight_sum:.3f}"))

    # Print table
    all_pass = True
    print(f"  {'#':<3} {'Check':<38} {'Status':<8} {'Fix'}")
    print(f"  {'-'*3} {'-'*38} {'-'*8} {'-'*40}")
    for i, (name, passed, fix) in enumerate(results, 1):
        status = "PASS" if passed else "FAIL"
        print(f"  {i:<3} {name:<38} {status:<8} {'' if passed else fix}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("All checks PASSED. System is ready.")
    else:
        print("Some checks FAILED. Fix the issues above and re-run.")
        sys.exit(1)

    return all_pass


def cmd_demo(record_mode: bool = False, scenario: str = None):
    """Run demo scenario(s)."""
    if not record_mode:
        require_api_key()

    from nightingale.core.openai_client import reset_openai_client
    if record_mode:
        os.environ["NIGHTINGALE_RECORD_MODE"] = "1"
        print("[record-mode] Using cached API responses only\n")
    reset_openai_client()

    from nightingale.demo.scenario import run_demo
    run_demo(record_mode=record_mode, scenario_id=scenario)


def cmd_server(host: str, port: int):
    """Start the full Nightingale server (webhook + dashboard)."""
    require_api_key()
    from nightingale.api.webhook import run_webhook_server
    print(f"Starting Nightingale Server on {host}:{port}")
    print(f"Dashboard: http://localhost:{port}/")
    print(f"API docs:  http://localhost:{port}/docs")
    run_webhook_server(host=host, port=port)


def cmd_webhook(host: str, port: int):
    """Alias for cmd_server (backward compat)."""
    cmd_server(host, port)


def main():
    from nightingale.config import config

    parser = argparse.ArgumentParser(
        description=f"Nightingale v{config.get('version')} - Autonomous CI SRE Agent"
    )
    parser.add_argument("--demo", action="store_true",
                        help="Run demo scenario (interactive picker)")
    parser.add_argument("--scenario", type=str, choices=["1", "2", "3"],
                        help="Run a specific demo scenario directly (1=assertion, 2=import, 3=logic)")
    parser.add_argument("--restore-demo", action="store_true",
                        help="Reset demo_repo files to broken state (for re-running demo)")
    parser.add_argument("--server", action="store_true",
                        help="Start webhook server + web dashboard")
    parser.add_argument("--webhook", action="store_true",
                        help="Alias for --server")
    parser.add_argument("--verify-api", action="store_true",
                        help="Verify OpenAI API key")
    parser.add_argument("--self-check", action="store_true",
                        help="Run full system diagnostic (9 checks)")
    parser.add_argument("--record-mode", action="store_true",
                        help="Replay cached API responses (no live calls)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")

    args = parser.parse_args()

    if args.restore_demo:
        from nightingale.demo.scenario import restore_demo_files
        restore_demo_files()
        print("Demo files restored to broken state. Ready to run --demo again.")
        return
    elif args.verify_api:
        cmd_verify_api()
    elif args.self_check:
        cmd_self_check()
    elif args.demo or args.scenario:
        cmd_demo(record_mode=args.record_mode, scenario=args.scenario)
    elif args.server or args.webhook:
        cmd_server(args.host, args.port)
    else:
        v = config.get("version", "1.0.0")
        print(f"""
Nightingale v{v} - Autonomous CI SRE Agent

Commands:
  python main.py --verify-api          Verify OpenAI API key
  python main.py --self-check          Run 9-point system diagnostic
  python main.py --demo                Interactive scenario picker (3 scenarios)
  python main.py --scenario 1          Run scenario 1: test assertion bug
  python main.py --scenario 2          Run scenario 2: broken import
  python main.py --scenario 3          Run scenario 3: logic bug
  python main.py --server              Start server + dashboard (http://localhost:8000)
  python main.py --server --port 9000  Custom port

Environment variables:
  OPENAI_API_KEY    (required) OpenAI API key
  GITHUB_TOKEN      (optional) GitHub token for PR creation
  GITHUB_REPO       (optional) "owner/repo" for PR creation
  SLACK_WEBHOOK_URL (optional) Slack incoming webhook for notifications
""")


if __name__ == "__main__":
    main()
