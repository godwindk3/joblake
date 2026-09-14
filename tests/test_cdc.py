import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from joblake.cdc import discovery_scope
from joblake.discovery import DiscoveryCrawler
from joblake.models import DiscoveryRecord
from joblake.pipeline import IngestionPipeline
import test_discovery as discovery_fixtures
import test_postgres_state as postgres_fixtures
import test_pipeline as pipeline_fixtures

NOW = postgres_fixtures.NOW


def config():
    return {'source': 'example', 'state': {'provider': 'postgres'}, 'cdc': {'enabled': True},
            'discovery': {'pagination': {'start_page': 1, 'page_param': 'page'},
                          'delay': {'min_seconds': 0, 'max_seconds': 0},
                          'targets': [{'name': 'all', 'base_url': 'https://example.com/jobs', 'params': {'category': 'it'}}]}}


class CoverageTests(unittest.TestCase):
    def crawl(self, *, strategy='detect_last_page', repeated=False, confirmed=False, empty=False,
              start=1, total=None, second_target=False, fail=False):
        cfg = config()
        cfg['discovery']['pagination'].update(strategy=strategy, start_page=start, max_auto_pages=4)
        if total:
            cfg['discovery']['pagination']['total_pages'] = total
        if second_target:
            cfg['discovery']['targets'].append({'name': 'other', 'base_url': 'https://example.com/other'})
        class Source(discovery_fixtures.FakeSource):
            def extract_last_page_number(self, html, listing_url):
                return 2
            def extract_job_urls(self, html, listing_url):
                number = int(listing_url.rsplit('=', 1)[-1])
                if empty or (strategy == 'until_empty' and number == 3 and not repeated):
                    return []
                return ['https://example.com/job/' + str(1 if repeated else number)]
        class Fetcher(discovery_fixtures.FakeFetcher):
            def fetch(self, url, params=None, **kwargs):
                if fail and params['page'] == 2:
                    raise RuntimeError('page failure')
                return replace(super().fetch(url, params, **kwargs), listing_end_confirmed=confirmed)
        class State:
            def __init__(self):
                self.coverage = []
            def start_discovery_target(self, **kwargs):
                return len(self.coverage) + 1
            def finish_discovery_target(self, *args, **kwargs):
                pass
            def upsert_discovered_jobs(self, *args):
                return 0
            def record_discovery_coverage(self, target_id, complete, reason):
                self.coverage.append((complete, reason))
        state = State()
        crawler = DiscoveryCrawler(cfg, Source(cfg), discovery_fixtures.FakeStorage(),
                                   fetcher_factory=lambda _: Fetcher(), state=state, run_id=1)
        if fail:
            with self.assertRaises(RuntimeError):
                crawler.run()
        else:
            crawler.run()
        return state.coverage

    def test_complete_detected_pages(self):
        self.assertEqual(self.crawl(), [(True, 'detected_last_page')])

    def test_partial_and_repeated_scans_never_qualify(self):
        for args in ({'total': 1}, {'start': 2}, {'repeated': True}, {'empty': True}, {'fail': True},
                     {'strategy': 'until_empty'}, {'strategy': 'until_empty', 'repeated': True}):
            with self.subTest(args=args):
                self.assertFalse(self.crawl(**args)[0][0])

    def test_only_confirmed_empty_terminal_qualifies(self):
        self.assertEqual(self.crawl(strategy='until_empty', confirmed=True), [(True, 'confirmed_empty')])

    def test_same_urls_across_targets_do_not_count_as_repeated_pages(self):
        self.assertEqual(self.crawl(strategy='until_empty', confirmed=True, second_target=True),
                         [(True, 'confirmed_empty'), (True, 'confirmed_empty')])

    def test_scope_excludes_transport_but_includes_filters(self):
        first = config()
        other = copy.deepcopy(first)
        other['discovery']['delay']['max_seconds'] = 200
        other['discovery']['proxy'] = {'enabled': True}
        self.assertEqual(discovery_scope(first), discovery_scope(other))
        other['discovery']['targets'][0]['params']['category'] = 'sales'
        self.assertNotEqual(discovery_scope(first), discovery_scope(other))


@unittest.skipUnless(os.environ.get('JOBLAKE_TEST_POSTGRES') == '1', 'PostgreSQL integration opt-in required')
class CdcTests(unittest.TestCase):
    setUpClass = classmethod(postgres_fixtures.PostgresStateTests.setUpClass.__func__)
    tearDownClass = classmethod(postgres_fixtures.PostgresStateTests.tearDownClass.__func__)
    setUp = postgres_fixtures.PostgresStateTests.setUp

    def scan(self, urls, cfg=None, complete=True, phase='discovery', finalize=True):
        cfg = cfg or config()
        run = self.state.start_run('example', NOW)
        self.state.prepare_cdc_run(run, phase, cfg)
        if phase in {'full', 'discovery'}:
            for target in cfg['discovery']['targets']:
                if not target.get('enabled', True):
                    continue
                tid = self.state.start_discovery_target(run_id=run, source='example', target_name=target['name'], started_at=NOW)
                records = [DiscoveryRecord('example', f'https://example.com/{url}', target['name'], target['base_url'], 1, NOW) for url in urls]
                self.state.upsert_discovered_jobs(records, run)
                self.state.finish_discovery_target(tid, status='completed', finished_at=NOW, detected_last_page=1,
                    fetched_page_count=1, discovered_url_count=len(urls), new_url_count=0, duplicate_url_count=0, empty_page_count=0)
                self.state.record_discovery_coverage(tid, complete, 'detected_last_page' if complete else 'repeated_page')
        summary = None
        if finalize:
            with self.state.source_run('example'):
                summary = self.state.finalize_cdc(run, NOW)
        return run, summary

    def jobs(self):
        with self.state._connect() as c:
            return {r['url'].rsplit('/',1)[-1]:r['listing_status'] for r in c.execute('SELECT url,listing_status FROM crawl_state.jobs').fetchall()}

    def events(self):
        with self.state._connect() as c:
            return c.execute('SELECT * FROM crawl_state.url_events ORDER BY id').fetchall()

    def test_baseline_expiration_reappearance_and_no_repeat(self):
        self.assertEqual(self.scan(['a','b'])[1]['status'], 'baseline')
        run, result = self.scan(['b','c'])
        self.assertEqual(result['expired'], 1)
        self.assertEqual(self.jobs(), {'a':'expired','b':'active','c':'active'})
        with self.state.source_run('example'):
            self.assertEqual(self.state.finalize_cdc(run, NOW), result)
        self.assertEqual(self.scan(['b','c'])[1]['expired'], 0)
        self.assertEqual(self.scan(['a','b','c'])[1]['reappeared'], 1)
        self.assertEqual([e['event_type'] for e in self.events()], ['EXPIRED','REAPPEARED'])

    def test_old_unknown_urls_never_expire_on_baseline(self):
        self.scan(['old'], complete=False)
        self.scan(['current'])
        self.assertEqual(self.jobs(), {'old':'unknown','current':'active'})
        self.assertEqual(self.events(), [])

    def test_incomplete_zero_and_non_discovery_do_not_expire(self):
        self.scan(['a','b'])
        for urls, kwargs in [(['b'], {'complete':False}), ([], {}), ([], {'phase':'parse'}), ([], {'phase':'detail'})]:
            self.scan(urls, **kwargs)
            self.assertEqual(self.jobs(), {'a':'active','b':'active'})
            self.assertEqual(self.events(), [])

    def test_changed_scope_creates_baseline_without_events(self):
        self.scan(['a','b'])
        other = config()
        other['discovery']['targets'][0]['params']['category'] = 'sales'
        self.assertEqual(self.scan(['c'], cfg=other)[1]['status'], 'baseline')
        self.assertEqual(self.jobs(), {'a':'unknown','b':'unknown','c':'active'})
        self.assertEqual(self.events(), [])

    def test_transaction_rollback_and_retry(self):
        self.scan(['a','b'])
        run, _ = self.scan(['b'], finalize=False)
        with self.state.source_run('example'), patch.object(self.state, '_finish_cdc', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                self.state.finalize_cdc(run, NOW)
        self.assertEqual(self.jobs(), {'a':'active','b':'active'})
        self.assertEqual(self.events(), [])
        with self.state.source_run('example'):
            self.assertEqual(self.state.finalize_cdc(run, NOW)['expired'], 1)

    def test_old_run_cannot_finalize_after_newer_discovery(self):
        self.scan(['a','b'])
        old, _ = self.scan(['b'], finalize=False)
        self.scan(['a','b'])
        with self.state.source_run('example'):
            self.assertEqual(self.state.finalize_cdc(old, NOW)['status'], 'skipped')
        self.assertEqual(self.events(), [])

    def test_mismatched_lock_rejected(self):
        run, _ = self.scan(['a'], finalize=False)
        with self.state.source_run('different'), self.assertRaises(RuntimeError):
            self.state.finalize_cdc(run, NOW)

    def test_detail_failure_does_not_undo_applied_cdc(self):
        self.scan(['a','b'])
        run, result = self.scan(['b'], phase='full')
        self.state.finish_run(run, status='failed', finished_at=NOW, discovered_url_count=1, new_url_count=0)
        with self.state.source_run('example'):
            self.assertEqual(self.state.finalize_cdc(run, NOW), result)
        self.assertEqual(self.jobs()['a'], 'expired')

    def test_missing_target_prevents_expiration(self):
        self.scan(['a','b'])
        run, _ = self.scan(['b'], finalize=False)
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.crawl_runs SET expected_targets='[\"all\",\"missing\"]' WHERE id=%s", (run,))
        with self.state.source_run('example'):
            self.assertEqual(self.state.finalize_cdc(run, NOW)['reason'], 'incomplete_targets')
        self.assertEqual(self.jobs()['a'], 'active')

    def test_pipeline_runs_cdc_before_details_and_never_for_parse(self):
        cfg = pipeline_fixtures.IngestionPipelineTests._config('unused')
        cfg['state']['provider'] = 'postgres'
        cfg['cdc'] = {'enabled': True}
        cfg['discovery']['pagination'].pop('total_pages')
        urls = ['https://example.com/a', 'https://example.com/b']
        class Source(pipeline_fixtures.PipelineSource):
            def extract_last_page_number(self, *args, **kwargs):
                return 1
            def extract_job_urls(self, *args, **kwargs):
                return list(urls)
        pipeline = IngestionPipeline(cfg, source=Source(cfg), state=self.state,
            storage=pipeline_fixtures.PipelineStorage(),
            fetcher_factory=lambda _: pipeline_fixtures.PipelineFetcher('discovery', []),
            parse_service_factory=lambda **_: pipeline_fixtures.PipelineParseService([]))
        self.assertEqual(pipeline.run('discovery'), 'completed')
        urls.pop(0)
        with patch.object(pipeline, '_run_details', side_effect=RuntimeError('detail crash')):
            with self.assertRaises(RuntimeError):
                pipeline.run('full')
        self.assertEqual(self.jobs(), {'a': 'expired', 'b': 'active'})
        self.assertEqual(pipeline.run('parse'), 'completed')
        with self.state._connect() as c:
            self.assertEqual([r['cdc_status'] for r in c.execute('SELECT cdc_status FROM crawl_state.crawl_runs ORDER BY id').fetchall()],
                             ['baseline', 'applied', 'not_applicable'])
