import argparse

from joblake.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run JobLake ingestion pipeline"
    )

    parser.add_argument(
        "--config",
        default="configs/topcv.yaml",
        help="Path to source configuration file",
    )

    args = parser.parse_args()

    run_pipeline(args.config)


if __name__ == "__main__":
    main()