import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError
from engine.report_builder import build_rules_report
from engine.product_rules import UnsupportedRecommendation
from gyanbuddy_insights.generation import generate, generate_with_provider, local_configuration
from gyanbuddy_insights.schema import InsightBundle, GeneratedInsightBundle


ROWS = [dict(student_id='private-id', student_name='Private Name', roll_no='private-roll',
             section='private-section', class_name='Class 7', subject='Science', chapter='Gravitation',
             correct=3, attempted=10, total_questions=10)]


@override_settings(INSIGHTS_PROVIDER='openai', INSIGHTS_OPENAI_API_KEY='test-key', INSIGHTS_OPENAI_MODEL='gpt-4o-mini')
class OpenAIGenerationTests(SimpleTestCase):
    def response(self, **changes):
        return SimpleNamespace(status='completed', output_parsed=InsightBundle.model_validate(
            build_rules_report(ROWS)['insights'])) if not changes else SimpleNamespace(**changes)

    @patch('openai.OpenAI')
    def test_three_roles_share_one_request_and_explicit_identity_stays_local(self, constructor):
        client = constructor.return_value.__enter__.return_value
        client.responses.parse.return_value = self.response()
        result = generate(ROWS)
        self.assertEqual(result['source'], 'openai')
        self.assertEqual(result['model'], 'gpt-4o-mini')
        self.assertEqual(set(result['insights']), {'parent', 'teacher', 'principal'})
        self.assertEqual(result['metrics']['student_name'], 'Private Name')
        constructor.assert_called_once_with(api_key='test-key', timeout=60.0, max_retries=0)
        client.responses.parse.assert_called_once()
        args = client.responses.parse.call_args.kwargs
        self.assertFalse(args['store'])
        self.assertIs(args['text_format'], GeneratedInsightBundle)
        for value in ('private-id', 'Private Name', 'private-roll', 'private-section'):
            self.assertNotIn(value, args['input'])
        self.assertIn('topic_results', json.loads(args['input']))

    @patch('openai.OpenAI')
    def test_refusal_and_incomplete_response_are_failures(self, constructor):
        client = constructor.return_value.__enter__.return_value
        for status in ('completed', 'incomplete', 'failed'):
            client.responses.parse.return_value = self.response(status=status, output_parsed=None)
            with self.subTest(status=status), self.assertRaises(ValueError):
                generate(ROWS)

    @patch('openai.OpenAI')
    def test_invalid_and_unsupported_reports_are_rejected(self, constructor):
        client = constructor.return_value.__enter__.return_value
        client.responses.parse.return_value = self.response(status='completed', output_parsed={})
        with self.assertRaises(ValidationError):
            generate(ROWS)
        report = build_rules_report(ROWS)['insights']
        report['parent']['actions'][0] = 'Watch a recorded lecture.'
        client.responses.parse.return_value = self.response(status='completed', output_parsed=report)
        with self.assertRaises(UnsupportedRecommendation):
            generate(ROWS)

    @patch('openai.OpenAI')
    def test_api_error_propagates_without_offline_fallback(self, constructor):
        constructor.return_value.__enter__.return_value.responses.parse.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            generate(ROWS)

    @patch('openai.OpenAI')
    def test_missing_configuration_never_calls_api(self, constructor):
        for config in (dict(provider='openai', model='gpt-4o-mini'), dict(provider='openai', key='test-key'), dict(provider='unknown')):
            with self.subTest(config=config), self.assertRaises(ValueError):
                generate_with_provider(ROWS, **config)
        constructor.assert_not_called()

    def test_environment_selection_and_explicit_offline_override(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-env'}, clear=True):
            self.assertEqual(local_configuration()['provider'], 'openai')
            self.assertEqual(local_configuration()['model'], 'gpt-4o-mini')
            with patch.dict(os.environ, {'INSIGHTS_PROVIDER': 'rules'}):
                self.assertEqual(local_configuration()['provider'], 'rules')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(local_configuration()['provider'], 'rules')

    def test_sdk_schema_requires_follow_up_and_has_no_defaults(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(GeneratedInsightBundle)
        self.assertNotIn('"default"', json.dumps(schema))
        fields = schema['$defs']['GeneratedInsight']['required']
        self.assertIn('follow_up', fields)
        self.assertIn('evidence_note', fields)

    @override_settings(INSIGHTS_OPENAI_API_KEY='', INSIGHTS_OPENAI_MODEL='')
    @patch('openai.OpenAI')
    def test_django_environment_key_and_model_fallback(self, constructor):
        constructor.return_value.__enter__.return_value.responses.parse.return_value = self.response()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'env-test-key', 'OPENAI_MODEL': 'configured-model'}):
            result = generate(ROWS)
        self.assertEqual(result['model'], 'configured-model')
        self.assertEqual(constructor.call_args.kwargs['api_key'], 'env-test-key')
