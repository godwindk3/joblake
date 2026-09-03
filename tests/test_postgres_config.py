import unittest
from unittest.mock import MagicMock

from joblake.parsing.models import ParsedJob
from joblake.postgres import (
    PostgresRepository,
    PostgresSettings,
)


class PostgresSettingsTests(unittest.TestCase):

    def test_uses_standard_environment_names_and_defaults(
        self,
    ) -> None:
        settings = PostgresSettings.from_config(
            {},
            environ={
                "POSTGRES_PASSWORD": "secret",
            },
        )

        self.assertEqual(settings.host, "localhost")
        self.assertEqual(settings.port, 5432)
        self.assertEqual(settings.database, "joblake")
        self.assertEqual(settings.user, "joblake")
        self.assertEqual(settings.password, "secret")

    def test_complete_config_accepts_custom_env_names(
        self,
    ) -> None:
        settings = PostgresSettings.from_config(
            {
                "source": "itviec",
                "postgres": {
                    "host_env": "JOBLAKE_PG_HOST",
                    "port_env": "JOBLAKE_PG_PORT",
                    "database_env": "JOBLAKE_PG_DATABASE",
                    "user_env": "JOBLAKE_PG_USER",
                    "password_env": "JOBLAKE_PG_PASSWORD",
                    "sslmode_env": "JOBLAKE_PG_SSLMODE",
                    "connect_timeout_seconds": 7,
                },
            },
            environ={
                "JOBLAKE_PG_HOST": "postgres.internal",
                "JOBLAKE_PG_PORT": "6543",
                "JOBLAKE_PG_DATABASE": "curated",
                "JOBLAKE_PG_USER": "writer",
                "JOBLAKE_PG_PASSWORD": "secret",
                "JOBLAKE_PG_SSLMODE": "require",
            },
        )

        self.assertEqual(settings.host, "postgres.internal")
        self.assertEqual(settings.port, 6543)
        self.assertEqual(settings.database, "curated")
        self.assertEqual(settings.user, "writer")
        self.assertEqual(settings.password, "secret")
        self.assertEqual(settings.sslmode, "require")
        self.assertEqual(settings.connect_timeout_seconds, 7)

    def test_environment_takes_precedence_over_literals(
        self,
    ) -> None:
        settings = PostgresSettings.from_config(
            {
                "host": "configured-host",
                "port": 5433,
                "database": "configured-db",
                "user": "configured-user",
                "password": "configured-password",
            },
            environ={
                "POSTGRES_HOST": "environment-host",
                "POSTGRES_PASSWORD": "environment-password",
            },
        )

        self.assertEqual(settings.host, "environment-host")
        self.assertEqual(settings.port, 5433)
        self.assertEqual(settings.database, "configured-db")
        self.assertEqual(settings.user, "configured-user")
        self.assertEqual(
            settings.password,
            "environment-password",
        )

    def test_missing_password_has_clear_error(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "POSTGRES_PASSWORD",
        ):
            PostgresSettings.from_config(
                {},
                environ={},
            )

    def test_port_and_timeout_must_be_positive(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "postgres.port",
        ):
            PostgresSettings.from_config(
                {
                    "port": "not-a-number",
                    "password": "secret",
                },
                environ={},
            )

        with self.assertRaisesRegex(
            ValueError,
            "postgres.connect_timeout_seconds",
        ):
            PostgresSettings.from_config(
                {
                    "password": "secret",
                    "connect_timeout_seconds": 0,
                },
                environ={},
            )

    def test_sqlalchemy_url_preserves_special_characters(
        self,
    ) -> None:
        settings = PostgresSettings(
            host="localhost",
            port=5432,
            database="joblake",
            user="user@name",
            password="p@ss:/?#% word",
            sslmode="require",
        )

        url = settings.sqlalchemy_url()

        self.assertEqual(url.username, "user@name")
        self.assertEqual(url.password, "p@ss:/?#% word")
        self.assertEqual(url.query["sslmode"], "require")
        rendered = url.render_as_string(
            hide_password=False
        )
        self.assertIn("user%40name", rendered)
        self.assertIn("p%40ss%3A%2F%3F%23%25", rendered)
        self.assertNotIn("p@ss:/?#%", rendered)

    def test_repository_does_not_connect_when_created(
        self,
    ) -> None:
        calls = []

        def connect(**kwargs):
            calls.append(kwargs)
            raise AssertionError("must stay lazy")

        settings = PostgresSettings.from_config(
            {},
            environ={"POSTGRES_PASSWORD": "secret"},
        )
        repository = PostgresRepository(
            settings,
            connect=connect,
        )

        self.assertIs(repository.settings, settings)
        self.assertEqual(calls, [])

    def test_repository_replay_keeps_existing_current_result(
        self,
    ) -> None:
        repository, connect, cursor = (
            self._repository_with_cursor()
        )
        cursor.fetchone.side_effect = [
            (1,),
            (2,),
            (2,),
            (9,),
        ]

        result = self._save_result(repository)
        statements = self._executed_statements(cursor)

        self.assertEqual(result.parse_result_id, 9)
        self.assertEqual(
            result.output_location,
            "postgres:core.job_parse_results/9",
        )
        self.assertFalse(any(
            statement.startswith(
                "INSERT INTO core.job_parse_results"
            )
            for statement in statements
        ))
        self.assertFalse(any(
            statement.startswith(
                "UPDATE core.job_parse_results"
            )
            for statement in statements
        ))
        connect.assert_called_once()

    def test_repository_promotes_only_a_new_result(
        self,
    ) -> None:
        repository, connect, cursor = (
            self._repository_with_cursor()
        )
        cursor.fetchone.side_effect = [
            (1,),
            (2,),
            (2,),
            None,
            (3,),
        ]

        result = self._save_result(repository)
        statements = self._executed_statements(cursor)
        insert_index = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith(
                "INSERT INTO core.job_parse_results"
            )
        )
        demote_index = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith(
                "UPDATE core.job_parse_results"
            )
            and "is_current = FALSE" in statement
        )
        promote_index = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith(
                "UPDATE core.job_parse_results"
            )
            and "is_current = TRUE" in statement
        )

        self.assertEqual(result.parse_result_id, 3)
        self.assertIn("FALSE", statements[insert_index])
        self.assertLess(insert_index, demote_index)
        self.assertLess(demote_index, promote_index)
        connect.assert_called_once()

    @staticmethod
    def _repository_with_cursor():
        connect = MagicMock()
        connection = connect.return_value.__enter__.return_value
        cursor = (
            connection.cursor.return_value
            .__enter__.return_value
        )
        settings = PostgresSettings.from_config(
            {},
            environ={"POSTGRES_PASSWORD": "secret"},
        )
        repository = PostgresRepository(
            settings,
            connect=connect,
        )
        return repository, connect, cursor

    @staticmethod
    def _save_result(
        repository: PostgresRepository,
    ):
        return repository.save_parse_result(
            source="itviec",
            canonical_url=(
                "https://itviec.com/it-jobs/backend-123"
            ),
            crawler_job_id=10,
            first_seen_at="2026-09-01T00:00:00+00:00",
            last_seen_at="2026-09-02T00:00:00+00:00",
            raw_object_id=20,
            raw_provider="minio",
            raw_bucket="joblake",
            raw_object_key="raw/detail/source=itviec/a.html",
            raw_object_version=None,
            raw_sha256="a" * 64,
            fetched_at="2026-09-02T00:01:00+00:00",
            parser_name="itviec",
            parser_version="1.0.0",
            parsed_job=ParsedJob(
                title="Backend Developer",
                employer_name_raw="Example Company",
                description_text="Build backend services",
            ),
            quality_status="accepted",
            completeness_score=90,
            missing_fields=[],
            warnings=[],
            parsed_at="2026-09-03T00:00:00+00:00",
        )

    @staticmethod
    def _executed_statements(cursor) -> list[str]:
        return [
            " ".join(call.args[0].split())
            for call in cursor.execute.call_args_list
        ]


if __name__ == "__main__":
    unittest.main()
