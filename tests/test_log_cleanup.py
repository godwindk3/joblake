import tempfile
import unittest
from pathlib import Path

from joblake.log_cleanup import cleanup


class LogCleanupTests(unittest.TestCase):
    def test_only_old_finished_known_logs_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {}
            for name in ("old", "active", "unknown", "fresh", "reopened"):
                path = root / "dag_id=joblake_itviec" / f"run_id={name}" / "task_id=detail" / "attempt=1.log"
                path.parent.mkdir(parents=True)
                path.write_text("log")
                paths[name] = path
            old = "2000-01-01T00:00:00+00:00"
            rows = [{"run_id": name, "state": "running" if name == "active" else "success", "end_date": old}
                    for name in paths if name != "unknown"]
            rows[2]["end_date"] = "2100-01-01T00:00:00+00:00"  # fresh
            calls = 0

            def get_runs(_):
                nonlocal calls
                calls += 1
                return [dict(r, state="running") if calls > 1 and r["run_id"] == "reopened" else r for r in rows]

            now = 2000000000
            self.assertEqual(cleanup(root, now=now, get_runs=get_runs)[0], 1)
            self.assertTrue(paths["old"].exists())
            calls = 0
            self.assertEqual(cleanup(root, now=now, apply=True, get_runs=get_runs)[0], 1)
            self.assertFalse(paths["old"].exists())
            self.assertTrue(all(p.exists() for n, p in paths.items() if n != "old"))

    def test_bad_retention_and_cli_failure_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                cleanup(tmp, 0)
            (Path(tmp) / "dag_id=joblake_itviec").mkdir()
            with self.assertRaises(RuntimeError):
                cleanup(tmp, apply=True, get_runs=lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
