import hashlib
import io
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from joblake.models import (
    DiscoveryRecord,
    FetchResult,
    StorageIntegrityError,
)


def _safe_name(value: str) -> str:
    return re.sub(
        pattern=r"[^a-zA-Z0-9_-]",
        repl="_",
        string=value,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _detail_url_hash(record: DiscoveryRecord) -> str:
    identity = f"{record.source}:{record.url}"
    return hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ObjectLocator:
    provider: str
    bucket_name: str
    object_key: str
    object_version: str | None = None


@dataclass(frozen=True, slots=True)
class RawObjectPayload:
    locator: ObjectLocator
    content: bytes
    content_type: str
    content_sha256: str

    @property
    def content_length_bytes(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class StoredObject:
    locator: ObjectLocator
    content_length_bytes: int
    content_sha256: str
    stored_at: str
    etag: str | None = None


class RawStorage(Protocol):

    def read_object(
        self,
        locator: ObjectLocator,
    ) -> bytes: ...

    def save_discovery(
        self,
        *,
        source: str,
        target_name: str,
        page_number: int,
        fetch_result: FetchResult,
    ) -> StoredObject | None: ...

    def prepare_detail(
        self,
        *,
        discovery_record: DiscoveryRecord,
        fetch_result: FetchResult,
    ) -> RawObjectPayload: ...

    def save_prepared_detail(
        self,
        payload: RawObjectPayload,
    ) -> StoredObject: ...

    def stat_object(
        self,
        locator: ObjectLocator,
        *,
        expected_sha256: str,
    ) -> StoredObject | None: ...


class LocalRawStorage:

    def __init__(
        self,
        raw_directory: str,
        *,
        store_discovery: bool = True,
    ):
        self.raw_root = Path(raw_directory)
        self.store_discovery = store_discovery

    @classmethod
    def from_config(cls, config: dict):
        storage_config = config["storage"]
        return cls(
            storage_config["raw_directory"],
            store_discovery=storage_config.get(
                "store_discovery",
                True,
            ),
        )

    def save_discovery(
        self,
        *,
        source: str,
        target_name: str,
        page_number: int,
        fetch_result: FetchResult,
    ) -> StoredObject | None:
        if not self.store_discovery:
            return None

        fetched_at = datetime.fromisoformat(
            fetch_result.fetched_at
        )
        crawl_date = fetched_at.date().isoformat()
        timestamp = fetched_at.strftime(
            "%Y%m%dT%H%M%S%f"
        )
        path = (
            self.raw_root
            / f"source={_safe_name(source)}"
            / "entity=discovery"
            / f"crawl_date={crawl_date}"
            / f"target={_safe_name(target_name)}"
            / f"page={page_number}_{timestamp}.html"
        )
        content = fetch_result.html.encode("utf-8")
        payload = RawObjectPayload(
            locator=ObjectLocator(
                provider="local",
                bucket_name="local",
                object_key=str(path),
            ),
            content=content,
            content_type=(
                fetch_result.content_type
                or "text/html; charset=utf-8"
            ),
            content_sha256=_content_sha256(content),
        )
        return self._write_payload(payload)

    def read_object(
        self,
        locator: ObjectLocator,
    ) -> bytes:
        return Path(locator.object_key).read_bytes()

    def prepare_detail(
        self,
        *,
        discovery_record: DiscoveryRecord,
        fetch_result: FetchResult,
    ) -> RawObjectPayload:
        object_path = (
            self.raw_root
            / f"source={_safe_name(discovery_record.source)}"
            / "entity=detail"
            / f"{_detail_url_hash(discovery_record)}.html"
        )
        content = fetch_result.html.encode("utf-8")

        return RawObjectPayload(
            locator=ObjectLocator(
                provider="local",
                bucket_name="local",
                object_key=str(object_path),
            ),
            content=content,
            content_type=(
                fetch_result.content_type
                or "text/html; charset=utf-8"
            ),
            content_sha256=_content_sha256(content),
        )

    def save_prepared_detail(
        self,
        payload: RawObjectPayload,
    ) -> StoredObject:
        return self._write_payload(payload)

    def save_detail(
        self,
        *,
        discovery_record: DiscoveryRecord,
        fetch_result: FetchResult,
    ) -> StoredObject:
        return self.save_prepared_detail(
            self.prepare_detail(
                discovery_record=discovery_record,
                fetch_result=fetch_result,
            )
        )

    def stat_object(
        self,
        locator: ObjectLocator,
        *,
        expected_sha256: str,
    ) -> StoredObject | None:
        path = Path(locator.object_key)

        if not path.is_file():
            return None

        content = path.read_bytes()
        return StoredObject(
            locator=locator,
            content_length_bytes=len(content),
            content_sha256=_content_sha256(content),
            stored_at=datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        )

    @staticmethod
    def _write_payload(
        payload: RawObjectPayload,
    ) -> StoredObject:
        path = Path(payload.locator.object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(
            f".{path.name}.{uuid.uuid4().hex}.tmp"
        )

        try:
            temporary_path.write_bytes(payload.content)
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return StoredObject(
            locator=payload.locator,
            content_length_bytes=(
                payload.content_length_bytes
            ),
            content_sha256=payload.content_sha256,
            stored_at=_utc_now(),
        )


class MinioRawStorage:

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool,
        prefix: str = "raw",
        store_discovery: bool = False,
        ensure_bucket: bool = True,
    ):
        try:
            from minio import Minio
            from minio.error import S3Error
        except ImportError as exc:
            raise RuntimeError(
                "MinIO storage requires the 'minio' package"
            ) from exc

        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._s3_error_type = S3Error
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.store_discovery = store_discovery

        if ensure_bucket and not self.client.bucket_exists(
            bucket_name
        ):
            self.client.make_bucket(bucket_name)

    @classmethod
    def from_config(cls, config: dict):
        storage_config = config["storage"]

        endpoint_env = storage_config.get(
            "endpoint_env",
            "MINIO_ENDPOINT",
        )
        raw_endpoint = (
            os.getenv(endpoint_env)
            or storage_config.get(
                "endpoint",
                "localhost:9000",
            )
        )
        endpoint_secure = False

        if "://" in raw_endpoint:
            parsed_endpoint = urlsplit(raw_endpoint)
            endpoint = parsed_endpoint.netloc
            endpoint_secure = (
                parsed_endpoint.scheme.lower() == "https"
            )
        else:
            endpoint = raw_endpoint
        access_key_env = storage_config.get(
            "access_key_env",
            "MINIO_ROOT_USER",
        )
        secret_key_env = storage_config.get(
            "secret_key_env",
            "MINIO_ROOT_PASSWORD",
        )
        access_key = os.getenv(access_key_env)
        secret_key = os.getenv(secret_key_env)

        if not access_key or not secret_key:
            raise ValueError(
                "Missing MinIO credentials in "
                f"{access_key_env}/{secret_key_env}"
            )

        return cls(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=storage_config.get(
                "bucket_name",
                "joblake",
            ),
            secure=bool(
                storage_config.get(
                    "secure",
                    endpoint_secure,
                )
            ),
            prefix=storage_config.get(
                "prefix",
                "raw",
            ),
            store_discovery=storage_config.get(
                "store_discovery",
                False,
            ),
            ensure_bucket=storage_config.get(
                "ensure_bucket",
                True,
            ),
        )

    def save_discovery(
        self,
        *,
        source: str,
        target_name: str,
        page_number: int,
        fetch_result: FetchResult,
    ) -> StoredObject | None:
        if not self.store_discovery:
            return None

        fetched_at = datetime.fromisoformat(
            fetch_result.fetched_at
        )
        timestamp = fetched_at.strftime(
            "%Y%m%dT%H%M%S%f"
        )
        crawl_date = fetched_at.date().isoformat()
        object_key = (
            f"{self.prefix}/discovery/"
            f"source={_safe_name(source)}/"
            f"crawl_date={crawl_date}/"
            f"target={_safe_name(target_name)}/"
            f"page={page_number}_{timestamp}.html"
        )
        content = fetch_result.html.encode("utf-8")
        payload = RawObjectPayload(
            locator=ObjectLocator(
                provider="minio",
                bucket_name=self.bucket_name,
                object_key=object_key,
            ),
            content=content,
            content_type=(
                fetch_result.content_type
                or "text/html; charset=utf-8"
            ),
            content_sha256=_content_sha256(content),
        )
        return self._put_payload(payload)

    def read_object(
        self,
        locator: ObjectLocator,
    ) -> bytes:
        response = self.client.get_object(
            locator.bucket_name,
            locator.object_key,
            version_id=locator.object_version,
        )

        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def prepare_detail(
        self,
        *,
        discovery_record: DiscoveryRecord,
        fetch_result: FetchResult,
    ) -> RawObjectPayload:
        object_key = (
            f"{self.prefix}/detail/"
            f"source={_safe_name(discovery_record.source)}/"
            f"{_detail_url_hash(discovery_record)}.html"
        )
        content = fetch_result.html.encode("utf-8")

        return RawObjectPayload(
            locator=ObjectLocator(
                provider="minio",
                bucket_name=self.bucket_name,
                object_key=object_key,
            ),
            content=content,
            content_type=(
                fetch_result.content_type
                or "text/html; charset=utf-8"
            ),
            content_sha256=_content_sha256(content),
        )

    def save_prepared_detail(
        self,
        payload: RawObjectPayload,
    ) -> StoredObject:
        return self._put_payload(payload)

    def save_detail(
        self,
        *,
        discovery_record: DiscoveryRecord,
        fetch_result: FetchResult,
    ) -> StoredObject:
        return self.save_prepared_detail(
            self.prepare_detail(
                discovery_record=discovery_record,
                fetch_result=fetch_result,
            )
        )

    def stat_object(
        self,
        locator: ObjectLocator,
        *,
        expected_sha256: str,
    ) -> StoredObject | None:
        try:
            stat = self.client.stat_object(
                locator.bucket_name,
                locator.object_key,
                version_id=locator.object_version,
            )
        except self._s3_error_type as exc:
            if exc.code in {
                "NoSuchKey",
                "NoSuchObject",
                "NoSuchBucket",
                "NoSuchVersion",
            }:
                return None
            raise

        return StoredObject(
            locator=ObjectLocator(
                provider="minio",
                bucket_name=locator.bucket_name,
                object_key=locator.object_key,
                object_version=getattr(
                    stat,
                    "version_id",
                    None,
                ),
            ),
            content_length_bytes=stat.size,
            content_sha256=expected_sha256,
            stored_at=(
                stat.last_modified.isoformat()
                if stat.last_modified
                else _utc_now()
            ),
            etag=getattr(stat, "etag", None),
        )

    def _put_payload(
        self,
        payload: RawObjectPayload,
    ) -> StoredObject:
        result = self.client.put_object(
            payload.locator.bucket_name,
            payload.locator.object_key,
            io.BytesIO(payload.content),
            payload.content_length_bytes,
            content_type=payload.content_type,
        )
        stored = self.stat_object(
            ObjectLocator(
                provider="minio",
                bucket_name=payload.locator.bucket_name,
                object_key=payload.locator.object_key,
                object_version=getattr(
                    result,
                    "version_id",
                    None,
                ),
            ),
            expected_sha256=payload.content_sha256,
        )

        if stored is None:
            raise StorageIntegrityError(
                "MinIO object is missing after upload"
            )

        if (
            stored.content_length_bytes
            != payload.content_length_bytes
        ):
            raise StorageIntegrityError(
                "MinIO object size does not match upload"
            )

        return StoredObject(
            locator=stored.locator,
            content_length_bytes=(
                stored.content_length_bytes
            ),
            content_sha256=payload.content_sha256,
            stored_at=stored.stored_at,
            etag=stored.etag,
        )


def create_raw_storage(config: dict) -> RawStorage:
    provider = config["storage"].get(
        "provider",
        "local",
    )

    if provider == "local":
        return LocalRawStorage.from_config(config)

    if provider == "minio":
        return MinioRawStorage.from_config(config)

    raise ValueError(
        f"Unsupported storage provider: {provider}"
    )


def save_raw_discovery(
    *,
    source: str,
    target_name: str,
    page_number: int,
    fetch_result: FetchResult,
    config: dict,
) -> StoredObject | None:
    """Backward-compatible functional API."""
    return create_raw_storage(config).save_discovery(
        source=source,
        target_name=target_name,
        page_number=page_number,
        fetch_result=fetch_result,
    )


def save_raw_detail(
    *,
    discovery_record: DiscoveryRecord,
    fetch_result: FetchResult,
    config: dict,
) -> StoredObject:
    """Backward-compatible functional API."""
    storage = create_raw_storage(config)
    payload = storage.prepare_detail(
        discovery_record=discovery_record,
        fetch_result=fetch_result,
    )
    return storage.save_prepared_detail(payload)
