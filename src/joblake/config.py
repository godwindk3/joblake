from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    config_path = Path(path)

    with config_path.open(
        mode="r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    if not config.get("enabled", True):
        raise ValueError(
            f"Source {config.get('source')} is disabled"
        )

    if not config.get("source"):
        raise ValueError("Missing source name")

    return config