"""Import/report regressions. All writes stay in a temporary data directory."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import app
from engine.analytics import import_and_normalize_csv, load_test_data, analyze_student


class ImportReportTests(unittest.TestCase):
    def setUp(self):
        self.original_cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.provider = patch.object(app.generator, 'active_provider', 'SMART_MOCK')
        self.provider.start()
        self.client = TestClient(app.app)

    def tearDown(self):
        self.client.close()
        self.provider.stop()
        os.chdir(self.original_cwd)
        self.temp.cleanup()

    def upload(self, text):
        return self.client.post('/api/upload-csv', files={'file': ('results.csv', text.encode(), 'text/csv')})

    def test_repeated_student_decimal_marks_and_dynamic_reports(self):
        result = self.upload(
            'Student Name,Class,Section,Subject,Chapter,Marks,Out of\n'
            'Asha,7,B,English,Poetry,2.5,10\n'
            'Asha,7,B,English,Grammar,8,10\n'
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['total_students'], 1)
        roster = self.client.get('/api/students').json()['students']
        self.assertEqual(len(roster), 1)
        self.assertEqual(roster[0]['overall_accuracy_pct'], 52.5)
        sid = roster[0]['student_id']
        parent = self.client.get(f'/api/reports/parent/{sid}').json()
        self.assertEqual(parent['metrics']['total_tests_taken'], 2)
        self.assertIsNone(parent['metrics']['chapter_diagnostics'][0]['delta'])
        self.assertIn('Poetry', parent['ai_insight']['focus_area_explanation'])
        self.assertEqual(self.client.get('/api/report-groups').json()['groups'], [
            {'class_name': 'Class 7', 'section': 'B', 'subject': 'English'}
        ])
        teacher = self.client.get('/api/reports/teacher/Class%207/B/English').json()
        self.assertIn('Class 7-B', teacher['ai_insight']['subject_class_overview'])
        self.assertNotIn('Gravitation', json.dumps(teacher))
        principal = self.client.get('/api/reports/principal').json()
        self.assertEqual(principal['metrics']['curriculum_bottlenecks'][0]['average_pct'], 25)
        self.assertNotIn('Grade 9', principal['ai_insight']['executive_summary'])

    def test_invalid_upload_preserves_previous_data_and_cache(self):
        self.upload('Name,Score,Total\nAsha,8,10\n')
        cache = Path('data/generated_reports_cache.json')
        cache.write_text('{"kept": true}')
        original = Path('data/students_test_data.json').read_bytes()
        for score, total, attempted in [('11', '10', '10'), ('-1', '10', '10'), ('2', '0', '0'), ('oops', '10', '10'), ('inf', '10', '10'), ('5', '10', '3')]:
            with self.subTest(score=score, total=total, attempted=attempted):
                result = self.upload(f'Name,Score,Total,Attempted\nAsha,{score},{total},{attempted}\n')
                self.assertEqual(result.status_code, 400)
                self.assertIn('Row 2', result.json()['detail'])
                self.assertEqual(Path('data/students_test_data.json').read_bytes(), original)
                self.assertTrue(cache.exists())

    def test_missing_columns_and_names_fail(self):
        for text in ['Name,Score\nAsha,8\n', 'Name,Score,Total\n,8,10\n', 'Name,Score,Total\n']:
            self.assertEqual(self.upload(text).status_code, 400)
        self.assertFalse(Path('data/students_test_data.json').exists())

    def test_leading_zero_ids_and_namesakes(self):
        result = self.upload('Name,Student ID,Score,Total\nAsha,001,8,10\nAsha,002,7,10\n')
        self.assertEqual(result.json()['total_students'], 2)
        self.assertEqual([r['student_id'] for r in load_test_data()], ['001', '002'])

    def test_roll_numbers_are_scoped_to_class(self):
        result = self.upload('Name,Roll No,Class,Score,Total\nAsha,01,7,8,10\nRavi,01,8,7,10\n')
        self.assertEqual(result.json()['total_students'], 2)
        rows = load_test_data()
        self.assertNotEqual(rows[0]['student_id'], rows[1]['student_id'])
        self.assertEqual(rows[0]['roll_no'], '01')

    def test_conflicting_id_rejected(self):
        result = self.upload('Name,Student ID,Score,Total\nAsha,001,8,10\nRavi,001,7,10\n')
        self.assertEqual(result.status_code, 400)

    def test_excel_parser_uses_same_validation(self):
        # Exercise the Excel parser route without authoring a workbook fixture.
        frame = pd.DataFrame({'Name': ['Asha'], 'Student ID': ['001'], 'Score': ['7.5'], 'Total': ['10']})
        with patch('engine.analytics.pd.read_csv', side_effect=ValueError('binary workbook')), patch('engine.analytics.pd.read_excel', return_value=frame):
            result = import_and_normalize_csv(b'workbook', is_bytes=True)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(analyze_student('001')['overall_accuracy_pct'], 75)

    def test_mastered_records_do_not_invent_bottlenecks(self):
        self.upload('Name,Score,Total\nAsha,9,10\n')
        principal = self.client.get('/api/reports/principal').json()
        self.assertEqual(principal['ai_insight']['top_bottlenecks'], [])
        self.assertEqual(principal['metrics']['curriculum_bottlenecks'], [])
        self.assertNotIn('Gravitation', json.dumps(principal))

    def test_unknown_metadata_and_revision_focus(self):
        self.upload('Name,Score,Total\nAsha,6,10\n')
        row = load_test_data()[0]
        self.assertEqual(row['class_name'], 'Unspecified class')
        self.assertEqual(row['test_date'], '')
        parent = self.client.get(f"/api/reports/parent/{row['student_id']}").json()
        self.assertIn('60.0%', parent['ai_insight']['focus_area_explanation'])
        self.assertNotIn('Mrs. Sunita', json.dumps(parent))

    def test_batch_blocks_data_replacement(self):
        with patch.object(app.batch_worker, 'is_running', True):
            self.assertEqual(self.upload('Name,Score,Total\nAsha,8,10\n').status_code, 409)


if __name__ == '__main__':
    unittest.main()
