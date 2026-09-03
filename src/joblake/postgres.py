import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy import URL

from joblake.parsing.models import ParsedJob


_DEFAULT_ENV_NAMES = {
    "host": "POSTGRES_HOST",
    "port": "POSTGRES_PORT",
    "database": "POSTGRES_DB",
    "user": "POSTGRES_USER",
    "password": "POSTGRES_PASSWORD",
    "sslmode": "POSTGRES_SSLMODE",
}


@dataclass(frozen=True, slots=True)
class PostgresSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_timeout_seconds: int = 10
    sslmode: str | None = None
    application_name: str = "joblake-parser"

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "PostgresSettings":
        """Resolve PostgreSQL settings without loading a dotenv file.

        ``config`` may be either the complete source configuration or
        its ``postgres`` section. Environment variable names can be
        overridden with keys such as ``host_env`` and ``password_env``.
        Environment values take precedence over literal config values.
        """
        raw_config = config or {}
        postgres_config = _postgres_section(raw_config)
        environment = os.environ if environ is None else environ

        def resolve(
            field_name: str,
            default: str | None = None,
        ) -> str | None:
            environment_name = str(
                postgres_config.get(
                    f"{field_name}_env",
                    _DEFAULT_ENV_NAMES[field_name],
                )
            )
            environment_value = environment.get(
                environment_name
            )

            if environment_value not in {None, ""}:
                return environment_value

            configured_value = postgres_config.get(
                field_name,
                default,
            )

            if configured_value is None:
                return None

            return str(configured_value)

        password_environment = str(
            postgres_config.get(
                "password_env",
                _DEFAULT_ENV_NAMES["password"],
            )
        )
        password = resolve("password")

        if not password:
            raise ValueError(
                "Missing PostgreSQL password in "
                f"{password_environment}"
            )

        port = _positive_integer(
            resolve("port", "5432"),
            field_name="postgres.port",
        )
        connect_timeout = _positive_integer(
            postgres_config.get(
                "connect_timeout_seconds",
                10,
            ),
            field_name=(
                "postgres.connect_timeout_seconds"
            ),
        )

        return cls(
            host=resolve("host", "localhost")
            or "localhost",
            port=port,
            database=resolve("database", "joblake")
            or "joblake",
            user=resolve("user", "joblake")
            or "joblake",
            password=password,
            connect_timeout_seconds=connect_timeout,
            sslmode=resolve("sslmode"),
            application_name=str(
                postgres_config.get(
                    "application_name",
                    "joblake-parser",
                )
            ),
        )

    def connection_kwargs(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            "connect_timeout": (
                self.connect_timeout_seconds
            ),
            "application_name": self.application_name,
        }

        if self.sslmode:
            values["sslmode"] = self.sslmode

        return values

    def sqlalchemy_url(self) -> URL:
        """Build an encoded URL that is safe for special characters."""
        query = (
            {"sslmode": self.sslmode}
            if self.sslmode
            else {}
        )
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query=query,
        )


@dataclass(frozen=True, slots=True)
class PostgresWriteResult:
    source_posting_id: int
    parse_result_id: int
    output_location: str


class PostgresRepository:
    """Writes accepted parser output to PostgreSQL transactionally."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._connect = connect or psycopg.connect

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        environ: Mapping[str, str] | None = None,
        connect: Callable[..., Any] | None = None,
    ) -> "PostgresRepository":
        return cls(
            PostgresSettings.from_config(
                config,
                environ=environ,
            ),
            connect=connect,
        )

    def save_parse_result(
        self,
        *,
        source: str,
        canonical_url: str,
        crawler_job_id: int,
        first_seen_at: str | datetime,
        last_seen_at: str | datetime,
        raw_object_id: int,
        raw_provider: str,
        raw_bucket: str,
        raw_object_key: str,
        raw_object_version: str | None,
        raw_sha256: str,
        fetched_at: str | datetime,
        parser_name: str,
        parser_version: str,
        parsed_job: ParsedJob,
        quality_status: str,
        completeness_score: int,
        missing_fields: Sequence[str],
        warnings: Sequence[Mapping[str, Any] | str],
        parsed_at: str | datetime | None = None,
    ) -> PostgresWriteResult:
        """Write one immutable parsed result and make new data current."""
        effective_parsed_at = (
            parsed_at
            or datetime.now(timezone.utc)
        )
        base_url = _base_url(canonical_url)

        with self._connect(
            **self.settings.connection_kwargs()
        ) as connection:
            with connection.cursor() as cursor:
                source_id = self._upsert_source(
                    cursor,
                    code=source,
                    base_url=base_url,
                )
                source_posting_id = (
                    self._upsert_source_posting(
                        cursor,
                        source_id=source_id,
                        canonical_url=canonical_url,
                        crawler_job_id=crawler_job_id,
                        parsed_job=parsed_job,
                        first_seen_at=first_seen_at,
                        last_seen_at=last_seen_at,
                    )
                )

                # Serialize competing writes for one source posting so
                # the partial unique current-result index is respected.
                cursor.execute(
                    """
                    SELECT id
                    FROM core.source_job_postings
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (source_posting_id,),
                )
                locked_posting = cursor.fetchone()

                if locked_posting is None:
                    raise RuntimeError(
                        "Source posting disappeared before parse write"
                    )

                parse_result_id = self._find_result(
                    cursor,
                    source_posting_id=source_posting_id,
                    raw_sha256=raw_sha256,
                    parser_name=parser_name,
                    parser_version=parser_version,
                )

                if parse_result_id is None:
                    parse_result_id = self._insert_result(
                        cursor,
                        source_posting_id=source_posting_id,
                        raw_object_id=raw_object_id,
                        raw_provider=raw_provider,
                        raw_bucket=raw_bucket,
                        raw_object_key=raw_object_key,
                        raw_object_version=raw_object_version,
                        raw_sha256=raw_sha256,
                        fetched_at=fetched_at,
                        parser_name=parser_name,
                        parser_version=parser_version,
                        parsed_job=parsed_job,
                        quality_status=quality_status,
                        completeness_score=completeness_score,
                        missing_fields=missing_fields,
                        warnings=warnings,
                        parsed_at=effective_parsed_at,
                    )
                    self._make_result_current(
                        cursor,
                        source_posting_id=source_posting_id,
                        parse_result_id=parse_result_id,
                    )

        return PostgresWriteResult(
            source_posting_id=source_posting_id,
            parse_result_id=parse_result_id,
            output_location=(
                "postgres:core.job_parse_results/"
                f"{parse_result_id}"
            ),
        )

    @staticmethod
    def _upsert_source(
        cursor: Any,
        *,
        code: str,
        base_url: str | None,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO ref.sources AS existing (
                code,
                display_name,
                base_url
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET
                base_url = COALESCE(
                    EXCLUDED.base_url,
                    existing.base_url
                ),
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (code, code, base_url),
        )
        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "PostgreSQL did not return a source id"
            )

        return int(row[0])

    @staticmethod
    def _upsert_source_posting(
        cursor: Any,
        *,
        source_id: int,
        canonical_url: str,
        crawler_job_id: int,
        parsed_job: ParsedJob,
        first_seen_at: str | datetime,
        last_seen_at: str | datetime,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO core.source_job_postings AS existing (
                source_id,
                canonical_url,
                source_external_job_id,
                crawler_job_id,
                first_seen_at,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, canonical_url)
            DO UPDATE SET
                source_external_job_id = COALESCE(
                    EXCLUDED.source_external_job_id,
                    existing.source_external_job_id
                ),
                crawler_job_id = EXCLUDED.crawler_job_id,
                first_seen_at = LEAST(
                    existing.first_seen_at,
                    EXCLUDED.first_seen_at
                ),
                last_seen_at = GREATEST(
                    existing.last_seen_at,
                    EXCLUDED.last_seen_at
                ),
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                source_id,
                canonical_url,
                parsed_job.source_external_job_id,
                crawler_job_id,
                first_seen_at,
                last_seen_at,
            ),
        )
        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "PostgreSQL did not return a source posting id"
            )

        return int(row[0])

    @staticmethod
    def _find_result(
        cursor: Any,
        *,
        source_posting_id: int,
        raw_sha256: str,
        parser_name: str,
        parser_version: str,
    ) -> int | None:
        cursor.execute(
            """
            SELECT id
            FROM core.job_parse_results
            WHERE source_posting_id = %s
              AND raw_sha256 = %s
              AND parser_name = %s
              AND parser_version = %s
            FOR UPDATE
            """,
            (
                source_posting_id,
                raw_sha256,
                parser_name,
                parser_version,
            ),
        )
        row = cursor.fetchone()
        return int(row[0]) if row is not None else None

    @staticmethod
    def _insert_result(
        cursor: Any,
        *,
        source_posting_id: int,
        raw_object_id: int,
        raw_provider: str,
        raw_bucket: str,
        raw_object_key: str,
        raw_object_version: str | None,
        raw_sha256: str,
        fetched_at: str | datetime,
        parser_name: str,
        parser_version: str,
        parsed_job: ParsedJob,
        quality_status: str,
        completeness_score: int,
        missing_fields: Sequence[str],
        warnings: Sequence[Mapping[str, Any] | str],
        parsed_at: str | datetime,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO core.job_parse_results (
                source_posting_id,
                crawler_raw_object_id,
                raw_storage_provider,
                raw_bucket,
                raw_object_key,
                raw_object_version,
                raw_sha256,
                fetched_at,
                parser_name,
                parser_version,
                parsed_at,
                quality_status,
                completeness_score,
                missing_fields,
                warnings,
                title,
                employer_name_raw,
                source_variant,
                description_text,
                requirements_text,
                benefits_text,
                domains_raw,
                categories_raw,
                skills_raw,
                locations_raw,
                benefit_items,
                salary_raw,
                employment_type_raw,
                experience_raw,
                posted_at,
                expires_at,
                source_payload,
                is_current
            )
            VALUES (
                %(source_posting_id)s,
                %(crawler_raw_object_id)s,
                %(raw_storage_provider)s,
                %(raw_bucket)s,
                %(raw_object_key)s,
                %(raw_object_version)s,
                %(raw_sha256)s,
                %(fetched_at)s,
                %(parser_name)s,
                %(parser_version)s,
                %(parsed_at)s,
                %(quality_status)s,
                %(completeness_score)s,
                %(missing_fields)s,
                %(warnings)s,
                %(title)s,
                %(employer_name_raw)s,
                %(source_variant)s,
                %(description_text)s,
                %(requirements_text)s,
                %(benefits_text)s,
                %(domains_raw)s,
                %(categories_raw)s,
                %(skills_raw)s,
                %(locations_raw)s,
                %(benefit_items)s,
                %(salary_raw)s,
                %(employment_type_raw)s,
                %(experience_raw)s,
                %(posted_at)s,
                %(expires_at)s,
                %(source_payload)s,
                FALSE
            )
            RETURNING id
            """,
            {
                "source_posting_id": source_posting_id,
                "crawler_raw_object_id": raw_object_id,
                "raw_storage_provider": raw_provider,
                "raw_bucket": raw_bucket,
                "raw_object_key": raw_object_key,
                "raw_object_version": raw_object_version,
                "raw_sha256": raw_sha256,
                "fetched_at": fetched_at,
                "parser_name": parser_name,
                "parser_version": parser_version,
                "parsed_at": parsed_at,
                "quality_status": quality_status,
                "completeness_score": completeness_score,
                "missing_fields": list(missing_fields),
                "warnings": Jsonb(list(warnings)),
                "title": parsed_job.title,
                "employer_name_raw": (
                    parsed_job.employer_name_raw
                ),
                "source_variant": parsed_job.source_variant,
                "description_text": (
                    parsed_job.description_text
                ),
                "requirements_text": (
                    parsed_job.requirements_text
                ),
                "benefits_text": parsed_job.benefits_text,
                "domains_raw": list(parsed_job.domains_raw),
                "categories_raw": list(
                    parsed_job.categories_raw
                ),
                "skills_raw": list(parsed_job.skills_raw),
                "locations_raw": list(
                    parsed_job.locations_raw
                ),
                "benefit_items": list(
                    parsed_job.benefit_items
                ),
                "salary_raw": parsed_job.salary_raw,
                "employment_type_raw": (
                    parsed_job.employment_type_raw
                ),
                "experience_raw": parsed_job.experience_raw,
                "posted_at": parsed_job.posted_at,
                "expires_at": parsed_job.expires_at,
                "source_payload": Jsonb(
                    parsed_job.source_payload
                ),
            },
        )
        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "PostgreSQL did not return a parse result id"
            )

        return int(row[0])

    @staticmethod
    def _make_result_current(
        cursor: Any,
        *,
        source_posting_id: int,
        parse_result_id: int,
    ) -> None:
        cursor.execute(
            """
            UPDATE core.job_parse_results
            SET
                is_current = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE source_posting_id = %s
              AND id <> %s
              AND is_current = TRUE
            """,
            (source_posting_id, parse_result_id),
        )
        cursor.execute(
            """
            UPDATE core.job_parse_results
            SET
                is_current = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (parse_result_id,),
        )


def create_postgres_repository(
    config: Mapping[str, Any],
) -> PostgresRepository:
    """Create a lazy repository from application configuration."""
    return PostgresRepository.from_config(config)


def _postgres_section(
    config: Mapping[str, Any],
) -> Mapping[str, Any]:
    nested = config.get("postgres")

    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ValueError(
                "postgres configuration must be a mapping"
            )
        return nested

    postgres_keys = {
        "host",
        "port",
        "database",
        "user",
        "password",
        "sslmode",
        "host_env",
        "port_env",
        "database_env",
        "user_env",
        "password_env",
        "sslmode_env",
        "connect_timeout_seconds",
        "application_name",
    }

    if postgres_keys.intersection(config):
        return config

    return {}


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a positive integer"
        ) from exc

    if parsed < 1:
        raise ValueError(
            f"{field_name} must be a positive integer"
        )

    return parsed


def _base_url(url: str) -> str | None:
    parsed = urlsplit(url)

    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}"
