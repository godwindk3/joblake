import json
from dataclasses import asdict
from pathlib import Path

from joblake.models import DiscoveryRecord


def save_discovered_jobs(
    path: str,
    records: dict[str, DiscoveryRecord],
) -> None:
    file_path = Path(path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with file_path.open(
        mode="w",
        encoding="utf-8",
    ) as file:
        for record in records.values():
            file.write(
                json.dumps(
                    asdict(record),
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_crawled_urls(path: str) -> set[str]:
    file_path = Path(path)

    if not file_path.exists():
        return set()

    with file_path.open(
        mode="r",
        encoding="utf-8",
    ) as file:
        return {
            line.strip()
            for line in file
            if line.strip()
        }


def append_crawled_url(
    path: str,
    url: str,
) -> None:
    file_path = Path(path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with file_path.open(
        mode="a",
        encoding="utf-8",
    ) as file:
        file.write(f"{url}\n")