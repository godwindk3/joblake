import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, Self

from joblake.models import DiscoveryRecord


class StateStore(Protocol):

    def save_discovered_jobs(
        self,
        records: dict[str, DiscoveryRecord],
    ) -> None: ...

    def load_crawled_urls(self) -> set[str]: ...

    def mark_crawled(self, url: str) -> None: ...


class FileStateStore:

    def __init__(
        self,
        discovered_jobs_file: str,
        crawled_urls_file: str,
    ):
        self.discovered_jobs_file = Path(
            discovered_jobs_file
        )
        self.crawled_urls_file = Path(
            crawled_urls_file
        )

    @classmethod
    def from_config(cls, config: dict) -> Self:
        state_config = config["state"]

        return cls(
            discovered_jobs_file=state_config[
                "discovered_jobs_file"
            ],
            crawled_urls_file=state_config[
                "crawled_urls_file"
            ],
        )

    def save_discovered_jobs(
        self,
        records: dict[str, DiscoveryRecord],
    ) -> None:
        self.discovered_jobs_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.discovered_jobs_file.open(
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

    def load_crawled_urls(self) -> set[str]:
        if not self.crawled_urls_file.exists():
            return set()

        with self.crawled_urls_file.open(
            mode="r",
            encoding="utf-8",
        ) as file:
            return {
                line.strip()
                for line in file
                if line.strip()
            }

    def mark_crawled(self, url: str) -> None:
        self.crawled_urls_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.crawled_urls_file.open(
            mode="a",
            encoding="utf-8",
        ) as file:
            file.write(f"{url}\n")


def save_discovered_jobs(
    path: str,
    records: dict[str, DiscoveryRecord],
) -> None:
    """Backward-compatible functional API."""
    store = FileStateStore(path, path)
    store.save_discovered_jobs(records)


def load_crawled_urls(path: str) -> set[str]:
    """Backward-compatible functional API."""
    return FileStateStore(path, path).load_crawled_urls()


def append_crawled_url(
    path: str,
    url: str,
) -> None:
    """Backward-compatible functional API."""
    FileStateStore(path, path).mark_crawled(url)
