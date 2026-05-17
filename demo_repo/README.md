# demo_repo

This directory simulates a target repository for Nightingale SRE demos.

Each file contains an intentionally broken test that Nightingale diagnoses and fixes autonomously during a demo run.

| File | Bug | Scenario |
|------|-----|----------|
| `test_app.py` | Wrong expected value in assertion | Scenario 1 |
| `test_formatter.py` | `DefaultDict` instead of `defaultdict` (ImportError) | Scenario 2 |
| `test_fibonacci.py` | Off-by-one in Fibonacci sequence | Scenario 3 |

Run a demo:

```bash
python main.py --scenario 1
python main.py --scenario 2
python main.py --scenario 3
```

After each run, restore to broken state with:

```bash
python main.py --restore-demo
```
