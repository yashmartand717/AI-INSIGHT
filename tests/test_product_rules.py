import unittest
from engine.ai_generator import clean_json_response
from engine.product_rules import validate_recommendations, UnsupportedRecommendation
from engine.prompt_templates import PARENT_SYSTEM_PROMPT, TEACHER_SYSTEM_PROMPT, PRINCIPAL_SYSTEM_PROMPT


class ProductRulesTests(unittest.TestCase):
    def test_all_audiences_know_product_limit(self):
        for prompt in (PARENT_SYSTEM_PROMPT, TEACHER_SYSTEM_PROMPT, PRINCIPAL_SYSTEM_PROMPT):
            self.assertIn('does not provide recorded lectures', prompt)

    def test_recorded_lecture_recommendations_rejected(self):
        for text in ('Watch the recorded lecture on fractions.', 'Replay pre-recorded mathematics lessons.', 'Open lecture recordings in GyanBuddy.', 'Watch a video lesson in the app.'):
            with self.subTest(text=text), self.assertRaises(UnsupportedRecommendation):
                validate_recommendations({'actions': [text]})

    def test_supported_actions_and_recorded_marks_allowed(self):
        validate_recommendations({'summary': 'Review the recorded marks.', 'actions': ['Practise textbook questions.', 'Ask the teacher to explain fractions.']})

    def test_standalone_cloud_json_cannot_bypass_guard(self):
        with self.assertRaises(UnsupportedRecommendation):
            clean_json_response('{"action_plan_for_home": ["Watch recorded lectures."]}')
