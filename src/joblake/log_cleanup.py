"""Conservative Airflow task-log retention. Run with Airflow's Python/CLI."""
import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import subprocess
import time

LOGGER = logging.getLogger(__name__)
DAG_IDS = tuple(f"joblake_{s}" for s in (
    "itviec", "topcv", "topdev", "vietnamworks", "log_cleanup",
))


def list_runs(dag_id):
    result = subprocess.run(
        ["airflow", "dags", "list-runs", dag_id, "-o", "json"],
        check=True, capture_output=True, text=True, timeout=120,
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("Unexpected Airflow run list")
    return rows


def finished_before(run, cutoff):
    if run.get("state") not in {"success", "failed"} or not run.get("end_date"):
        return False
    ended = datetime.fromisoformat(run["end_date"].replace("Z", "+00:00"))
    return ended.tzinfo is not None and ended.timestamp() < cutoff


def cleanup(root, days=14, *, apply=False, now=None, get_runs=list_runs):
    if days < 1:
        raise ValueError("Retention must be at least one day")
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Log root must be an existing non-symlink directory")
    root = root.resolve()
    cutoff = (time.time() if now is None else now) - days * 86400
    count = total = 0
    for dag_id in DAG_IDS:
        folder = root / f"dag_id={dag_id}"
        if folder.is_symlink() or not folder.is_dir():
            continue
        runs = {r["run_id"]: r for r in get_runs(dag_id)}
        for run_dir in folder.iterdir():
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            run_id = run_dir.name.removeprefix("run_id=")
            if not run_dir.name.startswith("run_id=") or not finished_before(runs.get(run_id, {}), cutoff):
                continue
            # Only known task-log layout. Never recurse into arbitrary directories.
            files = []
            for task_dir in run_dir.iterdir():
                if task_dir.is_symlink() or not task_dir.is_dir() or not task_dir.name.startswith("task_id="):
                    continue
                files.extend(p for p in task_dir.glob("attempt=*.log")
                             if not p.is_symlink() and p.is_file())
            if not files or any(p.stat().st_mtime >= cutoff for p in files):
                continue
            # Recheck immediately before deletion; reopened/cleared runs are skipped.
            latest = {r["run_id"]: r for r in get_runs(dag_id)}
            if not finished_before(latest.get(run_id, {}), cutoff):
                continue
            for path in files:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError("Unsafe log path")
                size = path.stat().st_size
                if apply:
                    path.unlink()
                count += 1
                total += size
            # Leave directories in place; never recursively delete log trees.
    LOGGER.info("Log cleanup: mode=%s files=%s bytes=%s retention_days=%s",
                "apply" if apply else "dry-run", count, total, days)
    return count, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/opt/airflow/logs")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    cleanup(args.root, args.days, apply=args.apply)


if __name__ == "__main__":
    main()
