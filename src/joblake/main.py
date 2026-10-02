import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from joblake.logging import configure_logging


LOGGER = logging.getLogger(__name__)


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
        choices=("full", "discovery", "detail", "parse", "enrich", "enrich-backfill", "supabase-test", "supabase-setup", "supabase-enrichment-setup", "supabase-migrate", "supabase-sync", "supabase-verify"),
        default="full",
        help=(
            "Run discovery plus detail, discovery only, "
            "detail only, parse raw HTML, or test/migrate/sync/verify Supabase. "
            "Supabase phases process all sources; --config applies only to ingestion."
        ),
    )

    parser.add_argument("--preflight-only", action="store_true", help="Check migration without restoring")
    parser.add_argument('--enrichment-config', default='configs/enrichment.yaml')
    parser.add_argument('--max-jobs', type=int, help='Enrich: API attempts; enrich-backfill: distinct selected jobs')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Report without database writes or enrichment API calls')
    mode.add_argument('--execute', action='store_true', help='Execute enrich-backfill (defaults to dry run)')
    parser.add_argument('--backfill-options', help='Backfill parameters as a JSON object (used by Airflow)')
    parser.add_argument('--lookback-days', type=int)
    parser.add_argument('--date-from', help='Inclusive ISO date/time; naive values use Vietnam time')
    parser.add_argument('--date-to', help='Exclusive ISO date/time; naive values use Vietnam time')
    parser.add_argument('--as-of', help='Freeze the backfill window at this ISO timestamp')
    parser.add_argument('--date-field', choices=('first_seen_at', 'posted_at', 'fetched_at'))
    parser.add_argument('--sources', nargs='+', help='Source codes for enrich-backfill')
    parser.add_argument('--posting-ids', nargs='+', type=int)
    parser.add_argument('--sort-order', choices=('newest_first', 'oldest_first'))
    parser.add_argument('--max-api-attempts', type=int)
    parser.add_argument(
        "--strict", action="store_true",
        help=(
            "Exit nonzero for blocked or failed ingestion runs. "
            "Suspicious runs remain successful so schedulers can continue "
            "with downstream phases."
        ),
    )
    parser.add_argument(
        "--log-level", type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO", help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)
    if args.preflight_only and args.phase != "supabase-migrate":
        parser.error("--preflight-only requires supabase-migrate")
    if args.dry_run and args.phase not in ('supabase-sync', 'enrich', 'enrich-backfill'):
        parser.error('--dry-run requires supabase-sync, enrich or enrich-backfill')
    if args.max_jobs is not None and args.phase not in ('enrich', 'enrich-backfill'):
        parser.error('--max-jobs requires enrich or enrich-backfill')
    backfill_keys = ('lookback_days', 'date_from', 'date_to', 'as_of', 'date_field',
                     'sources', 'posting_ids', 'sort_order', 'max_api_attempts')
    if args.phase != 'enrich-backfill' and (args.execute or args.backfill_options is not None or any(
            getattr(args, key) is not None for key in backfill_keys)):
        parser.error('Backfill parameters require enrich-backfill')
    if args.phase == 'enrich-backfill':
        from joblake.enrichment.backfill import run
        try:
            options = json.loads(args.backfill_options) if args.backfill_options is not None else {}
        except ValueError:
            parser.error('--backfill-options must contain valid JSON')
        if not isinstance(options, dict):
            parser.error('--backfill-options must be a JSON object')
        options.update({key: getattr(args, key) for key in (*backfill_keys, 'max_jobs')
                        if getattr(args, key) is not None})
        if args.dry_run or args.execute:
            options['dry_run'] = not args.execute
        raise SystemExit(run(args.enrichment_config, options=options))
    if args.phase == 'enrich':
        from joblake.enrichment.service import run
        raise SystemExit(run(args.enrichment_config, dry_run=args.dry_run, max_jobs=args.max_jobs))
    if args.strict and args.phase.startswith("supabase-"):
        parser.error("--strict applies only to ingestion phases")
    if args.phase.startswith("supabase-"):
        from joblake.supabase_sync import configure
        configure()
        if args.phase == 'supabase-enrichment-setup':
            from joblake.enrichment.serving import setup
            raise SystemExit(setup())
        if args.phase == "supabase-test":
            from joblake.supabase_connection import main as command
            raise SystemExit(command())
        if args.phase == "supabase-migrate":
            from joblake.supabase_migrate import main as command
            raise SystemExit(command(["--preflight-only"] if args.preflight_only else []))
        if args.phase == "supabase-verify":
            from joblake.supabase_sync import sync
            raise SystemExit(sync(verify_only=True))
        if args.phase == "supabase-setup":
            from joblake.supabase_serving_setup import main as command
            raise SystemExit(command())
        from joblake.supabase_sync import sync
        raise SystemExit(sync(dry_run=args.dry_run))

    from joblake.pipeline import run_pipeline
    status = run_pipeline(args.config, phase=args.phase)
    LOGGER.log(
        logging.INFO if status == "completed" else logging.WARNING,
        "Ingestion result: source_config=%s phase=%s status=%s",
        args.config, args.phase, status,
    )
    if args.strict and status in {"blocked", "failed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
