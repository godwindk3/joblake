"""CI integration entry point: skipped or undiscovered tests must not look green."""
import os
import unittest


def main():
    required = ('JOBLAKE_TEST_POSTGRES', 'JOBLAKE_TEST_SERVING', 'JOBLAKE_TEST_ENRICHMENT')
    if any(os.getenv(name) != '1' for name in required):
        raise SystemExit('Enable all three JOBLAKE_TEST_* integration flags on a test database')
    suite = unittest.defaultTestLoader.discover('tests')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
