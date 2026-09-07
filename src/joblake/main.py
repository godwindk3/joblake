import argparse
from pathlib import Path

from dotenv import load_dotenv



def main() -> None:
    project_root = Path(__file__).resolve().parents[2]

    load_dotenv(
        dotenv_path=project_root / ".env",
        override=False,
    )

    parser = argparse.ArgumentParser(
        description="Run JobLake ingestion pipeline"
    )

    parser.add_argument(
        "--config",
        default="configs/topcv.yaml",
        help="Path to source configuration file",
    )
    parser.add_argument(
        "--phase",
        choices=("full", "discovery", "detail", "parse", "supabase-test", "supabase-migrate", "supabase-sync", "supabase-verify"),
        default="full",
        help=(
            "Run discovery plus detail, discovery only, "
            "detail only, parse raw HTML, or test/migrate/sync/verify Supabase. "
            "Supabase phases process all sources; --config applies only to ingestion."
        ),
    )

    parser.add_argument("--preflight-only", action="store_true", help="Check migration without restoring")
    parser.add_argument("--dry-run", action="store_true", help="Validate sync and roll back row changes")
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit nonzero for blocked, failed or suspicious ingestion runs (for schedulers)",
    )
    args = parser.parse_args()
    if args.preflight_only and args.phase != "supabase-migrate":
        parser.error("--preflight-only requires supabase-migrate")
    if args.dry_run and args.phase != "supabase-sync":
        parser.error("--dry-run requires supabase-sync")
    if args.strict and args.phase.startswith("supabase-"):
        parser.error("--strict applies only to ingestion phases")
    if args.phase.startswith("supabase-"):
        from joblake.supabase_sync import configure
        configure()
        if args.phase == "supabase-test":
            from joblake.supabase_connection import main as command
            raise SystemExit(command())
        if args.phase == "supabase-migrate":
            from joblake.supabase_migrate import main as command
            raise SystemExit(command(["--preflight-only"] if args.preflight_only else []))
        if args.phase == "supabase-verify":
            from joblake.supabase_verify import main as command
            raise SystemExit(command())
        from joblake.supabase_sync import sync
        raise SystemExit(sync(dry_run=args.dry_run))

    from joblake.pipeline import run_pipeline
    status = run_pipeline(args.config, phase=args.phase)
    print(f"Ingestion result: source_config={args.config} phase={args.phase} status={status}")
    if args.strict and status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
