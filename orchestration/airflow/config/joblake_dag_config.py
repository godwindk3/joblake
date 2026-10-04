"""Shared DAG configuration on Airflow's config module path; no worker imports."""
from datetime import timedelta
from pathlib import Path

import yaml


ENRICHMENT_CONFIG = Path('/opt/joblake/configs/enrichment.yaml')


def enrichment_execution_timeout(config_path=None):
    """Read on every DAG parse so mounted YAML changes reach the scheduler."""
    path = ENRICHMENT_CONFIG if config_path is None else Path(config_path)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    seconds = config.get('max_run_seconds') if isinstance(config, dict) else None
    if type(seconds) is not int or seconds < 1:
        raise ValueError(f'{path}: max_run_seconds must be a positive integer')
    # Allow the final API request and worker setup/cleanup to finish gracefully.
    return timedelta(seconds=seconds, minutes=5)
