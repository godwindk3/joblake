import argparse
from pathlib import Path

from dotenv import load_dotenv

from joblake.pipeline import run_pipeline


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
        choices=("full", "discovery", "detail"),
        default="full",
        help=(
            "Run both phases, discovery only, "
            "or detail only"
        ),
    )

    args = parser.parse_args()

    run_pipeline(args.config, phase=args.phase)


if __name__ == "__main__":
    main()
