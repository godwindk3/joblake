"""Deterministic health thresholds; no database access or external notifications."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import yaml


DEFAULTS = {
    'freshness_hours': 48,
    'max_pending_fetch': 100,
    'max_parse_backlog': 100,
    'max_stuck_jobs': 0,
    'max_parse_error_pct': 20,
    'min_parse_jobs': 10,
}


def load_policy(path, sources):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) - {'defaults', 'sources'}:
        raise ValueError('Health policy must contain defaults and/or sources')
    defaults, overrides = config.get('defaults', {}), config.get('sources', {})
    if not isinstance(defaults, dict) or not isinstance(overrides, dict):
        raise ValueError('Health defaults and sources must be mappings')
    if set(overrides) - set(sources):
        raise ValueError('Health policy contains an unknown source')
    for values in [defaults, *overrides.values()]:
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError('Unknown health threshold')
        for key, value in values.items():
            if value is None and key != 'min_parse_jobs':
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f'{key} must be a finite nonnegative number')
            if key == 'min_parse_jobs' and (value < 1 or int(value) != value):
                raise ValueError('min_parse_jobs must be a positive integer')
            if key == 'max_parse_error_pct' and value > 100:
                raise ValueError('max_parse_error_pct must be at most 100')
    return {source: {**DEFAULTS, **defaults, **overrides.get(source, {})}
            for source in sources}


def evaluate(report, policy):
    """Only completed parses enter the error-rate denominator; partial is usable."""
    sections = report['sections']
    required = {'inventory', 'raw_and_backlog', 'current_parse_status',
                'freshness', 'parse_outcomes_in_window'}
    if not required.issubset(sections):
        raise ValueError('Report lacks health metrics; generate a new snapshot')
    alerts = []

    def alert(source, metric, observed, limit):
        alerts.append(dict(source=source, metric=metric, observed=observed, limit=limit))

    for source, limits in policy.items():
        rows = {name: [row for row in sections[name] if row['source'] == source]
                for name in required}
        inventory = next(iter(rows['inventory']), {})
        if not inventory.get('total_jobs'):
            alert(source, 'missing_inventory', 0, 'at least one job')
        metrics = {
            'max_pending_fetch': ('pending_fetch', inventory.get('pending_fetch', 0)),
            'max_parse_backlog': ('parse_backlog', sum(
                r['awaiting_usable_parse'] for r in rows['raw_and_backlog'])),
            'max_stuck_jobs': ('stuck_jobs', inventory.get('stuck_fetch', 0) + sum(
                r['stuck_parse'] for r in rows['current_parse_status'])),
        }
        for key, (metric, observed) in metrics.items():
            limit = limits[key]
            if limit is not None and observed > limit:
                alert(source, metric, observed, limit)
        freshness = limits['freshness_hours']
        if freshness is not None:
            for phase in ('discovery', 'detail', 'parse'):
                phases = {phase, 'full'} if phase != 'parse' else {phase}
                ages = [float(r['hours_since_success']) for r in rows['freshness']
                        if r['phase'] in phases and r['hours_since_success'] is not None]
                age = min(ages) if ages else None
                if age is None or age > freshness:
                    alert(source, phase + '_hours_since_success', age, freshness)
        outcomes = rows['parse_outcomes_in_window']
        total = sum(r['jobs'] for r in outcomes)
        errors = sum(r['jobs'] for r in outcomes if r['status'] != 'success')
        limit = limits['max_parse_error_pct']
        if limit is not None and total >= limits['min_parse_jobs']:
            rate = 100 * errors / total
            if rate > limit:
                alert(source, 'parse_error_pct', round(rate, 2), limit)
    return {'status': 'alert' if alerts else 'ok', 'alerts': alerts,
            'thresholds': policy}


def configured_sources(directory):
    sources = []
    for path in sorted(Path(directory).glob('*.yaml')):
        value = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or 'source' not in value:
            continue
        source = value['source']
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f'{path}: source must be a non-empty string')
        sources.append(source)
    if not sources or len(sources) != len(set(sources)):
        raise ValueError('Config directory must contain unique source YAML files')
    return sources


def check_latest(directory, policy, *, max_age_hours=30, now=None):
    """Timestamped filenames are UTC and sortable; never fall back from a broken latest file."""
    paths = sorted(Path(directory).glob('*.json'))
    if not paths:
        raise ValueError('No health snapshot exists')
    report = json.loads(paths[-1].read_text(encoding='utf-8'))
    captured = datetime.fromisoformat(report['captured_at'])
    if captured.tzinfo is None:
        raise ValueError('Snapshot timestamp must include a timezone')
    age = ((now or datetime.now(timezone.utc)) - captured).total_seconds() / 3600
    if age < -5 / 60 or age > max_age_hours:
        raise ValueError('Latest health snapshot is stale or dated in the future')
    if set(policy) - set(report['sources']):
        raise ValueError('Snapshot is missing configured sources')
    return paths[-1], evaluate(report, policy)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check the latest saved health report without DB access')
    parser.add_argument('--output-dir', default='data/state/reports/data_health')
    parser.add_argument('--config-dir', default='configs')
    parser.add_argument('--thresholds', default='configs/data_health.yaml')
    parser.add_argument('--max-report-age-hours', type=float, default=30)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_report_age_hours) or args.max_report_age_hours <= 0:
        parser.error('max report age must be finite and positive')
    try:
        policy = load_policy(args.thresholds, configured_sources(args.config_dir))
        path, health = check_latest(args.output_dir, policy, max_age_hours=args.max_report_age_hours)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f'HEALTH CHECK ERROR: {exc}')
        return 2
    print(f"Health: {health['status']} — {path}")
    for alert in health['alerts']:
        print('ALERT {source}: {metric}={observed}; limit={limit}'.format(**alert))
    return 1 if health['alerts'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
