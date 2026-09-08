# Log retention

- Both Compose stacks use Docker `local` logging, 10 MB per file and 3 files
  per container. Recreate existing containers to apply it; do not restart a
  running crawl just to change logging. Volumes are not removed.
- `joblake_log_cleanup` runs daily at 05:00 Asia/Ho_Chi_Minh, enabled on
  creation. Pause this DAG in Airflow to disable task-log cleanup.
- Task logs are retained for 14 days after a run ends, and files must also
  be older than 14 days. Only the four source DAGs and this maintenance DAG
  are in scope. Running/queued/unknown runs, symlinks and unrecognized files
  are skipped. Airflow state is rechecked before deleting each run's logs.
- Do not manually clear/reopen an old run concurrently with cleanup. Pause
  the maintenance DAG and wait for its active task to finish first.
- Only `task_id=*/attempt=*.log` files are deleted, not directories. Deleted
  logs cannot be recovered unless separately backed up. Airflow history stays
  visible but old log contents will no longer be available.
- The cleanup defaults to dry-run. Inspect candidates in the Airflow runtime:

  ```sh
  docker compose -f orchestration/airflow/compose.yaml exec airflow-scheduler bash -c 'PYTHONPATH=/opt/joblake/src python -m joblake.log_cleanup --days 14'
  ```

- Change `--days 14` in the maintenance DAG to adjust retention. The helper
  fails if it cannot read Airflow state; it does not guess which logs are safe.
- This does not clean Airflow metadata, SQLite, raw, diagnostics, browser state,
  or PostgreSQL data. DAG-processor file logs and orphan logs whose metadata
  has been deleted are deliberately excluded and need separate review.
- Docker rotation limits container stdout/stderr, not bind-mounted task logs.
