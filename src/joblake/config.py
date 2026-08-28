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

    source_adapter = config.get("source_adapter")

    if (
        source_adapter is not None
        and not isinstance(source_adapter, str)
    ):
        raise ValueError(
            "source_adapter must be a dotted class path"
        )

    return config
