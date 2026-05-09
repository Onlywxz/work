"""Run the full daily local update workflow."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("Update spot daily data", PROJECT_ROOT / "scripts" / "update_daily_data.py"),
    ("Update futures and basis data", PROJECT_ROOT / "scripts" / "plot_basis.py"),
    ("Backfill dashboard HTML", PROJECT_ROOT / "scripts" / "build_dashboard_html.py"),
]


def run_step(step_number: int, total_steps: int, name: str, script_path: Path) -> None:
    print(f"[{step_number}/{total_steps}] START: {name}")
    print(f"Running: {sys.executable} {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)

    if result.returncode != 0:
        print(f"[{step_number}/{total_steps}] FAILED: {name}", file=sys.stderr)
        print(f"Exit code: {result.returncode}", file=sys.stderr)
        raise SystemExit(result.returncode)

    print(f"[{step_number}/{total_steps}] DONE: {name}")


def main() -> None:
    total_steps = len(STEPS)
    print("Daily update workflow started.")

    for index, (name, script_path) in enumerate(STEPS, start=1):
        run_step(index, total_steps, name, script_path)

    print("Daily update workflow completed successfully.")


if __name__ == "__main__":
    main()
