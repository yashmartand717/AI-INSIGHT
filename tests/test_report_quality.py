"""Reports must stay useful without claiming more than uploaded marks establish."""
import json
import unittest
from engine.analytics import analyze_student, analyze_class_subject, analyze_school_principal
from engine.report_builder import build_rules_report
from engine.product_rules import validate_recommendations


def mark(**changes):
    return dict(student_id='001', student_name='Kavita Nair', class_name='Class 7', section='B',
                subject='Science', chapter='Gravitation', correct=3, total_questions=10,
                attempted=10) | changes


class ReportQualityTests(unittest.TestCase):
    def test_single_low_result_is_supportive_and_actionable_for_every_role(self):
        result = build_rules_report([mark()])
        for role, report in result['insights'].items():
            with self.subTest(role=role):
                self.assertIn('3 out of 10 (30%)', report['summary'])
                self.assertIn('Gravitation (Science)', report['focus'])
                self.assertEqual(len(report['actions']), 3)
                self.assertIn('one submitted result', report['evidence_note'])
                self.assertIn('No historical comparison', report['evidence_note'])
                self.assertTrue(report['follow_up'])
                self.assertNotIn('No topic has reached', report['strengths'])
                self.assertNotIn('test records', report['summary'])
        self.assertEqual(len({tuple(r['actions']) for r in result['insights'].values()}), 3)
        validate_recommendations(result)

    def test_zero_does_not_invent_strengths(self):
        report = build_rules_report([mark(correct=0)])['insights']['parent']
        self.assertIn('does not yet show', report['strengths'])
        self.assertNotIn('Some credit', report['strengths'])

    def test_high_scores_get_extension_instead_of_remediation(self):
        reports = build_rules_report([mark(correct=10)])['insights']
        for report in reports.values():
            self.assertIn('100%', report['strengths'])
            self.assertNotIn('Start with', report['focus'])
        self.assertIn('extension', ' '.join(reports['principal']['actions']))

    def test_repeated_topic_is_weighted_and_not_both_strength_and_gap(self):
        rows = [mark(correct=1, total_questions=2, attempted=2), mark(correct=9)]
        metrics = analyze_student('001', rows)
        self.assertEqual(metrics['overall_accuracy_pct'], 83.3)
        self.assertEqual(metrics['needs_revision'], [])
        self.assertEqual(len(metrics['strengths']), 1)
        result = build_rules_report(rows)['insights']['parent']
        self.assertIn('10 out of 12 (83.3%)', result['summary'])
        self.assertIn('83.3%', result['strengths'])
        self.assertIn('parts of the same assessment', result['evidence_note'])

    def test_priority_is_lowest_topic_even_when_no_critical_gap(self):
        result = build_rules_report([mark(chapter='Waves', correct=6.5), mark(correct=4.5)])
        self.assertIn('Gravitation', result['insights']['parent']['focus'])
        self.assertIn('4.5 out of 10', result['insights']['parent']['focus'])

    def test_teacher_counts_unique_students_in_repeated_topic(self):
        rows = [mark(correct=1), mark(correct=2), mark(student_id='002', student_name='Ravi', correct=9)]
        result = analyze_class_subject('Class 7', 'B', 'Science', rows)
        self.assertEqual(result['chapter_stats'][0]['total_students_tested'], 2)
        self.assertEqual(result['chapter_stats'][0]['struggling_count'], 1)
        self.assertEqual(result['remedial_clusters'][0]['students'][0]['score_pct'], 15)
        self.assertNotIn('formulas', json.dumps(result))

    def test_principal_percentage_counts_students_not_rows(self):
        rows = [mark(correct=1), mark(correct=2), mark(student_id='002', student_name='Ravi', correct=9)]
        result = analyze_school_principal(rows)['subject_breakdown'][0]
        self.assertEqual(result['critical_gap_students_pct'], 50)
        self.assertEqual(result['students_evaluated'], 2)

    def test_historical_comparison_is_qualified(self):
        report = build_rules_report([mark(previous_score_pct=20)])['insights']['parent']
        self.assertIn('check that the assessments are comparable', report['evidence_note'])
        self.assertNotIn('improved', report['summary'])
