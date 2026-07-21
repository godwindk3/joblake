import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from joblake.models import (
    DiscoveryRecord,
    FetchResult,
)


def _safe_name(value: str) -> str:
    return re.sub(
        pattern=r"[^a-zA-Z0-9_-]",
        repl="_",
        string=value,
    )


def _fetch_time_parts(
    fetched_at: str,
) -> tuple[str, str]:
    fetched_datetime = datetime.fromisoformat(
        fetched_at
    )

    crawl_date = fetched_datetime.date().isoformat()

    timestamp = fetched_datetime.strftime(
        "%Y%m%dT%H%M%S%f"
    )

    return crawl_date, timestamp


def _write_html_and_metadata(
    html_path: Path,
    metadata_path: Path,
    html: str,
    metadata: dict,
) -> tuple[str, str]:
    html_bytes = html.encode("utf-8")

    metadata = {
        **metadata,
        "content_length_bytes": len(html_bytes),
        "content_sha256": hashlib.sha256(
            html_bytes
        ).hexdigest(),
    }

    html_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    html_path.write_text(
        html,
        encoding="utf-8",
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return str(html_path), str(metadata_path)


def save_raw_discovery(
    *,
    source: str,
    target_name: str,
    page_number: int,
    fetch_result: FetchResult,
    config: dict,
) -> tuple[str, str]:
    raw_root = Path(
        config["storage"]["raw_directory"]
    )

    crawl_date, timestamp = _fetch_time_parts(
        fetch_result.fetched_at
    )

    directory = (
        raw_root
        / f"source={_safe_name(source)}"
        / "entity=discovery"
        / f"crawl_date={crawl_date}"
        / f"target={_safe_name(target_name)}"
    )

    file_stem = (
        f"page={page_number}_{timestamp}"
    )

    metadata = {
        "source": source,
        "entity_type": "discovery",
        "target_name": target_name,
        "listing_page": page_number,
        "requested_url": fetch_result.requested_url,
        "final_url": fetch_result.final_url,
        "status_code": fetch_result.status_code,
        "content_type": fetch_result.content_type,
        "fetched_at": fetch_result.fetched_at,
    }

    return _write_html_and_metadata(
        html_path=directory / f"{file_stem}.html",
        metadata_path=(
            directory / f"{file_stem}.metadata.json"
        ),
        html=fetch_result.html,
        metadata=metadata,
    )


def save_raw_detail(
    *,
    discovery_record: DiscoveryRecord,
    fetch_result: FetchResult,
    config: dict,
) -> tuple[str, str]:
    raw_root = Path(
        config["storage"]["raw_directory"]
    )

    crawl_date, timestamp = _fetch_time_parts(
        fetch_result.fetched_at
    )

    url_hash = hashlib.sha256(
        discovery_record.url.encode("utf-8")
    ).hexdigest()

    directory = (
        raw_root
        / f"source={_safe_name(discovery_record.source)}"
        / "entity=detail"
        / f"crawl_date={crawl_date}"
    )

    file_stem = f"{url_hash}_{timestamp}"

    metadata = {
        **asdict(discovery_record),
        "entity_type": "detail",
        "requested_url": fetch_result.requested_url,
        "final_url": fetch_result.final_url,
        "status_code": fetch_result.status_code,
        "content_type": fetch_result.content_type,
        "fetched_at": fetch_result.fetched_at,
    }

    return _write_html_and_metadata(
        html_path=directory / f"{file_stem}.html",
        metadata_path=(
            directory / f"{file_stem}.metadata.json"
        ),
        html=fetch_result.html,
        metadata=metadata,
    )