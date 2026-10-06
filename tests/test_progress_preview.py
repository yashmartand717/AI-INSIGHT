import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine.progress_preview import ProgressPreview


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'preview.sqlite3'
        self.store = ProgressPreview(self.path)
        self.records = [dict(student_id='001', student_name='Example', class_name='Class 7', section='B', subject='English', chapter='Poetry', correct=2.5, attempted=10, total_questions=10)]

    def tearDown(self):
        self.store.executor.shutdown(wait=True)
        self.temp.cleanup()

    def test_progress_and_report_persist(self):
        bid = self.store.start(self.records, background=False)
        self.assertEqual(self.store.get(bid)['report_states'], {'queued': 1})
        self.store.run(bid)
        result = self.store.get(bid)
        self.assertEqual(result['ready_students'], 1)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['results'][0]['report']['metrics']['overall_accuracy_pct'], 25)
        self.assertEqual(set(result['results'][0]['report']['insights']), {'parent', 'teacher', 'principal'})
        reopened = ProgressPreview(self.path)
        self.assertEqual(reopened.list()['results'][0]['ready_students'], 1)
        reopened.executor.shutdown()

    def test_active_job_is_reused_and_snapshots_are_separate(self):
        first = self.store.start(self.records, background=False)
        self.assertEqual(first, self.store.start(self.records, background=False))
        self.store.run(first)
        second = self.store.start(self.records, background=False)
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.list()['count'], 2)

    def test_restart_exposes_unfinished_work(self):
        bid = self.store.start(self.records, background=False)
        reopened = ProgressPreview(self.path)
        self.assertEqual(reopened.get(bid)['status'], 'failed')
        self.assertEqual(reopened.get(bid)['results'][0]['error_code'], 'PreviewRestarted')
        reopened.executor.shutdown()

    def test_failed_analysis_not_counted_ready(self):
        bid = self.store.start(self.records, background=False)
        with patch('engine.progress_preview.build_rules_report', side_effect=ValueError):
            self.store.run(bid)
        self.assertEqual(self.store.get(bid)['report_states'], {'failed': 1})
        self.assertEqual(self.store.get(bid)['email_states'], {})

    def test_cloud_builder_used_and_failure_is_visible(self):
        from engine.report_builder import build_rules_report
        from unittest.mock import Mock
        result = build_rules_report(self.records)
        result.update(source='openai', model='configured-model')
        self.store.builder = Mock(return_value=result)
        bid = self.store.start(self.records, background=False)
        self.store.run(bid)
        self.assertEqual(self.store.get(bid)['results'][0]['report']['source'], 'openai')
        self.store.builder.assert_called_once_with(self.records)
        self.store.builder.side_effect = TimeoutError()
        next_bid = self.store.start(self.records, background=False)
        self.store.run(next_bid)
        self.assertEqual(self.store.get(next_bid)['report_states'], {'failed': 1})
        self.assertEqual(self.store.get(next_bid)['results'][0]['error_code'], 'TimeoutError')

    def test_dashboard_configuration_does_not_expose_key(self):
        import os
        import app
        with patch.dict(os.environ, {'INSIGHTS_PROVIDER': 'openai', 'OPENAI_API_KEY': 'secret-test-key', 'OPENAI_MODEL': 'my-model'}):
            config = app.progress_config()
        self.assertEqual(config['provider'], 'openai')
        self.assertEqual(config['model'], 'my-model')
        self.assertNotIn('secret-test-key', str(config))

    def test_empty_and_unknown_jobs(self):
        with self.assertRaises(ValueError):
            self.store.start([])
        with self.assertRaises(KeyError):
            self.store.get('unknown')

    def test_refresh_saved_reports_preserves_original_marks_and_failed_rows(self):
        bid = self.store.start(self.records, background=False)
        self.store.run(bid)
        rows = self.store.get(bid)['results']
        rows[0]['report'].pop('report_version')
        rows[0]['report']['insights']['parent']['summary'] = 'Old report'
        rows.append(dict(student_id='failed', state='failed', error_code='ExistingFailure', report={}))
        self.store.save(bid, rows)
        with self.store.connect() as db:
            original = db.execute('SELECT records FROM batches WHERE id=?', (bid,)).fetchone()[0]
        self.assertEqual(self.store.refresh_ready_reports(), 1)
        self.assertEqual(self.store.refresh_ready_reports(), 0)
        result = self.store.get(bid)['results']
        self.assertNotEqual(result[0]['report']['insights']['parent']['summary'], 'Old report')
        self.assertEqual(result[1]['error_code'], 'ExistingFailure')
        self.assertEqual(len(list(self.path.parent.glob('*.before-*.sqlite3'))), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT records FROM batches WHERE id=?', (bid,)).fetchone()[0], original)

    def test_dashboard_api_generates_reports_without_email_transport(self):
        from fastapi.testclient import TestClient
        import app
        client = TestClient(app.app)
        with patch.object(app, 'progress_preview', self.store), patch.object(app, 'load_test_data', return_value=self.records):
            self.assertEqual(client.get('/progress').status_code, 200)
            self.assertFalse(client.get('/api/progress/config/').json()['can_send'])
            response = client.post('/api/progress/batches/')
            self.assertEqual(response.status_code, 202)
            bid = response.json()['id']
            self.store.executor.shutdown(wait=True)
            status = client.get(f'/api/progress/batches/{bid}/').json()
            self.assertEqual(status['ready_students'], 1)
            self.assertEqual(client.get('/api/progress/batches/').json()['count'], 1)
            self.assertEqual(client.get(f'/api/progress/batches/{bid}/reports/').json()['count'], 1)
            self.assertEqual(client.post(f'/api/progress/batches/{bid}/emails/').status_code, 405)
            self.assertEqual(client.get('/api/progress/batches/missing/').status_code, 404)
        client.close()
