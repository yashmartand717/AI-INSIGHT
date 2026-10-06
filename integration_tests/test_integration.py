from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from gyanbuddy_insights.access import AccessAdapter
from gyanbuddy_insights.models import Batch, StudentReport, EmailDelivery, DeliveryResolution
from gyanbuddy_insights.services import submit_marks, publish
from gyanbuddy_insights.tasks import generate_student, send_delivery, dispatch_pending


class TestAccess(AccessAdapter):
    def marks_for_report(self, school_id, reporting_id):
        if school_id != 'school-a' or reporting_id != 'exam-1':
            raise PermissionDenied('Exam is not available for this school')
        return payload()['records']

    def school_for(self, user):
        return "school-b" if user.username == "other-school" else "school-a"

    def can_manage(self, user, school_id):
        return user.is_staff

    def validate_records(self, school_id, records):
        if any(r["student_id"] not in {"001", "002"} for r in records):
            raise PermissionDenied("Unknown student")

    def recipients(self, school_id, student_ids):
        ids = set(student_ids)
        return [
            *[{"email": f"parent-{sid}@example.test", "role": "parent", "student_ids": [sid]} for sid in ids],
            {"email": "teacher@example.test", "role": "teacher", "student_ids": sorted(ids)},
            {"email": "principal@example.test", "role": "principal", "student_ids": sorted(ids)},
        ]


def payload(event="upload-1"):
    return {"event_id": event, "records": [
        {"record_id": "r1", "student_id": "001", "student_name": "Asha", "class_name": "Class 7", "section": "B", "subject": "English", "chapter": "Poetry", "correct": 2.5, "total_questions": 10},
        {"record_id": "r2", "student_id": "002", "student_name": "Ravi", "class_name": "Class 7", "section": "B", "subject": "English", "chapter": "Poetry", "correct": 9, "total_questions": 10},
    ]}


class IntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("school-admin", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def batch(self):
        return submit_marks(school_id="school-a", payload=payload())[0]

    def ready(self):
        batch = self.batch()
        for report in batch.reports.all():
            generate_student(str(report.pk))
        return batch

    def test_end_to_end_email_is_scoped_and_idempotent(self):
        response = self.client.post('/marks-uploaded/', payload(), format='json')
        self.assertEqual(response.status_code, 202)
        batch = Batch.objects.get(pk=response.data['id'])
        for r in batch.reports.all():
            generate_student(str(r.pk))
        self.assertEqual(self.client.get(f'/batches/{batch.pk}/').data['status'], 'ready')
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 202)
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 200)
        self.assertEqual(batch.deliveries.count(), 4)
        for delivery in batch.deliveries.all():
            send_delivery(str(delivery.pk))
            send_delivery(str(delivery.pk))
        self.assertEqual(len(mail.outbox), 4)
        for message in mail.outbox:
            self.assertIn('How to check progress', message.body)
            self.assertIn('What this report is based on', message.body)
            self.assertNotIn('No topic has reached', message.body)
            self.assertIn('How to check progress', message.alternatives[0][0])
        parent = next(m for m in mail.outbox if m.to == ['parent-001@example.test'])
        self.assertIn('Asha', parent.body)
        self.assertNotIn('Ravi', parent.body)
        teacher = next(m for m in mail.outbox if m.to == ['teacher@example.test'])
        self.assertIn('Asha', teacher.body)
        self.assertIn('Ravi', teacher.body)
        self.assertEqual(batch.deliveries.filter(state='sent').count(), 4)

    def test_no_delivery_before_click(self):
        batch = self.ready()
        self.assertEqual(batch.deliveries.count(), 0)

    @override_settings(INSIGHTS_PROVIDER='openai', INSIGHTS_OPENAI_API_KEY='test-key', INSIGHTS_OPENAI_MODEL='gpt-4o-mini')
    @patch('openai.OpenAI')
    def test_openai_reports_complete_worker_and_email_flow(self, constructor):
        from types import SimpleNamespace
        from engine.report_builder import build_rules_report
        from gyanbuddy_insights.schema import InsightBundle
        batch = self.batch()
        for report in batch.reports.all():
            constructor.return_value.__enter__.return_value.responses.parse.return_value = SimpleNamespace(
                status='completed', output_parsed=InsightBundle.model_validate(build_rules_report(report.records)['insights']))
            generate_student(str(report.pk))
            report.refresh_from_db()
            self.assertEqual(report.state, 'ready')
            self.assertEqual(report.result['source'], 'openai')
        publish(batch, self.user)
        for delivery in batch.deliveries.all():
            send_delivery(str(delivery.pk))
        self.assertEqual(len(mail.outbox), 4)
        self.assertTrue(all('OpenAI-assisted analysis' in message.body for message in mail.outbox))

    def test_dashboard_and_history_are_school_scoped(self):
        batch = self.ready()
        listing = self.client.get('/batches/')
        self.assertEqual(listing.data['count'], 1)
        self.assertEqual(listing.data['results'][0]['id'], str(batch.pk))
        self.assertEqual(self.client.get('/config/').data['mode'], 'django')
        page = self.client.get('/dashboard/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Report progress')
        other = get_user_model().objects.create_user('other-school', is_staff=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get('/batches/').data['count'], 0)

    def test_siblings_and_duplicate_recipient_entries_merge(self):
        batch = self.ready()
        plan = TestAccess().recipients('school-a', ['001', '002'])
        for item in plan:
            if item['role'] == 'parent':
                item['email'] = 'family@example.test'
        plan.append(plan[0])
        with patch.object(TestAccess, 'recipients', return_value=plan):
            publish(batch, self.user)
            delivery = batch.deliveries.get(role='parent')
            send_delivery(str(delivery.pk))
        self.assertEqual(delivery.student_ids, ['001', '002'])
        self.assertEqual(batch.deliveries.count(), 3)
        self.assertEqual(mail.outbox[0].to, ['family@example.test'])

    def test_email_reconciliation_requires_confirmation_and_records_operator(self):
        batch = self.ready()
        publish(batch, self.user)
        delivery = batch.deliveries.first()
        EmailDelivery.objects.filter(pk=delivery.pk).update(state='uncertain')
        with self.assertRaises(CommandError):
            call_command('insights_resolve_email', str(delivery.pk), action='retry', operator='admin', reason='Checked logs')
        call_command('insights_resolve_email', str(delivery.pk), action='retry', operator='admin', reason='Provider confirms not accepted', confirmed_not_sent=True, verbosity=0)
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'pending')
        self.assertEqual(DeliveryResolution.objects.get().operator, 'admin')

    def test_retry_command_queues_failed_generation_only(self):
        batch = self.batch()
        report = batch.reports.first()
        StudentReport.objects.filter(pk=report.pk).update(state='failed', attempts=3)
        call_command('insights_retry_batch', str(batch.pk), verbosity=0)
        report.refresh_from_db()
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.attempts, 0)

    def test_duplicate_event_and_changed_payload(self):
        first = self.client.post('/marks-uploaded/', payload(), format='json')
        duplicate = self.client.post('/marks-uploaded/', payload(), format='json')
        self.assertEqual(first.data['id'], duplicate.data['id'])
        modified = payload()
        modified['records'][0]['correct'] = 3
        self.assertEqual(self.client.post('/marks-uploaded/', modified, format='json').status_code, 409)
        self.assertEqual(StudentReport.objects.count(), 2)

    def test_validation_and_unknown_student(self):
        bad = payload()
        bad['records'][0]['correct'] = 11
        self.assertEqual(self.client.post('/marks-uploaded/', bad, format='json').status_code, 400)
        bad = payload()
        bad['records'][0]['student_id'] = 'unrelated'
        self.assertEqual(self.client.post('/marks-uploaded/', bad, format='json').status_code, 403)
        self.assertEqual(Batch.objects.count(), 0)

    def test_duplicate_record_ids_rejected(self):
        bad = payload()
        bad['records'][1]['record_id'] = 'r1'
        self.assertEqual(self.client.post('/marks-uploaded/', bad, format='json').status_code, 400)

    def test_other_school_cannot_read_or_send(self):
        batch = self.ready()
        other = get_user_model().objects.create_user('other-school', is_staff=True)
        self.client.force_authenticate(other)
        for suffix in ['', 'reports/', 'emails/']:
            self.assertEqual(self.client.get(f'/batches/{batch.pk}/{suffix}').status_code, 404)
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 404)

    def test_parent_and_anonymous_cannot_manage(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/marks-uploaded/', payload(), format='json').status_code, 401)
        parent = get_user_model().objects.create_user('parent')
        self.client.force_authenticate(parent)
        self.assertEqual(self.client.post('/marks-uploaded/', payload(), format='json').status_code, 403)

    def test_incomplete_batch_records_send_intent_without_sending_early(self):
        batch = self.batch()
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 202)
        self.assertEqual(EmailDelivery.objects.count(), 0)
        batch.refresh_from_db()
        self.assertIsNotNone(batch.send_requested_at)

    def dispatch_inline(self):
        # Exercise the real dispatcher/worker chain with no external broker.
        with patch('gyanbuddy_insights.tasks.generate_student.delay', side_effect=generate_student), patch('gyanbuddy_insights.tasks.send_delivery.delay', side_effect=send_delivery):
            dispatch_pending()

    def test_one_click_database_analysis_and_email_is_idempotent(self):
        response = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        self.assertEqual(response.status_code, 202)
        batch = Batch.objects.get(pk=response.data['id'])
        self.assertIsNotNone(batch.send_requested_at)
        self.assertEqual(batch.send_requested_by, str(self.user.pk))
        self.assertEqual(batch.deliveries.count(), 0)
        repeat = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.data['id'], str(batch.pk))
        self.dispatch_inline()
        batch.refresh_from_db()
        self.assertIsNotNone(batch.published_at)
        self.assertEqual(batch.deliveries.filter(state='sent').count(), 4)
        self.assertEqual(len(mail.outbox), 4)
        self.dispatch_inline()
        self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        self.assertEqual(len(mail.outbox), 4)
        parent = next(m for m in mail.outbox if m.to == ['parent-001@example.test'])
        self.assertIn('Asha', parent.body)
        self.assertNotIn('Ravi', parent.body)

    def test_database_send_denies_other_school_and_client_email_override(self):
        for body in ({'reporting_id': 'exam-1', 'email': 'wrong@example.test'}, {'reporting_id': ''}):
            self.assertEqual(self.client.post('/email-all-reports/', body, format='json').status_code, 400)
        other = get_user_model().objects.create_user('other-school', is_staff=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json').status_code, 403)
        self.assertEqual(Batch.objects.count(), 0)

    def test_database_snapshot_changes_create_a_new_revision(self):
        first = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        rows = payload()['records']
        rows[0]['correct'] = 5
        with patch.object(TestAccess, 'marks_for_report', return_value=rows):
            second = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(first.data['id'], second.data['id'])

    def test_missing_database_recipients_roll_back_entire_request(self):
        with patch.object(TestAccess, 'recipients', return_value=[]):
            response = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Batch.objects.count(), 0)

    def test_changed_recipients_block_auto_publication_and_can_be_corrected(self):
        response = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        batch = Batch.objects.get(pk=response.data['id'])
        with patch.object(TestAccess, 'recipients', return_value=[]):
            self.dispatch_inline()
        batch.refresh_from_db()
        self.assertEqual(batch.publication_error, 'Conflict')
        self.assertIsNone(batch.published_at)
        self.assertEqual(batch.deliveries.count(), 0)
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 202)
        self.dispatch_inline()
        self.assertEqual(len(mail.outbox), 4)

    def test_failed_report_blocks_requested_emails_until_repaired(self):
        response = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        batch = Batch.objects.get(pk=response.data['id'])
        report = batch.reports.first()
        report.state = 'failed'
        report.save(update_fields=['state'])
        self.dispatch_inline()
        self.assertEqual(batch.deliveries.count(), 0)
        report.state = 'queued'
        report.save(update_fields=['state'])
        self.dispatch_inline()
        self.assertEqual(len(mail.outbox), 4)

    def test_dispatcher_recovers_publication_after_generation_interruption(self):
        response = self.client.post('/email-all-reports/', {'reporting_id': 'exam-1'}, format='json')
        batch = Batch.objects.get(pk=response.data['id'])
        with patch('gyanbuddy_insights.tasks.finalize_requested_batch'):
            for report in batch.reports.all():
                generate_student(str(report.pk))
        self.assertEqual(batch.deliveries.count(), 0)
        self.dispatch_inline()
        self.assertEqual(len(mail.outbox), 4)

    def test_gmail_smtp_uses_tls_and_one_authorized_recipient(self):
        from gyanbuddy_insights.gmail import gmail_smtp_settings
        batch = self.ready()
        publish(batch, self.user)
        delivery = batch.deliveries.get(email='parent-001@example.test')
        config = gmail_smtp_settings({'GMAIL_SENDER_EMAIL': 'school@example.test', 'GMAIL_APP_PASSWORD': 'abcd efgh ijkl mnop'})
        with override_settings(**config), patch('smtplib.SMTP') as smtp:
            smtp.return_value.sendmail.return_value = {}
            send_delivery(str(delivery.pk))
            self.assertEqual(smtp.call_args.args[:2], ('smtp.gmail.com', 587))
            smtp.return_value.starttls.assert_called_once()
            smtp.return_value.login.assert_called_once_with('school@example.test', 'abcdefghijklmnop')
            args = smtp.return_value.sendmail.call_args.args
            self.assertEqual(args[1], ['parent-001@example.test'])
            self.assertNotIn(b'Ravi', args[2])
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'sent')

    def test_missing_email_blocks_entire_publish(self):
        batch = self.ready()
        with patch.object(TestAccess, 'recipients', return_value=[]):
            self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 409)
        self.assertEqual(EmailDelivery.objects.count(), 0)

    def test_membership_change_blocks_transmission(self):
        batch = self.ready()
        publish(batch, self.user)
        delivery = batch.deliveries.first()
        with patch.object(TestAccess, 'recipients', return_value=[]):
            send_delivery(str(delivery.pk))
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'blocked')

    def test_saved_recorded_lecture_advice_cannot_be_emailed(self):
        batch = self.ready()
        report = batch.reports.get(student_id='001')
        report.result['insights']['parent']['actions'] = ['Watch the recorded lecture in GyanBuddy.']
        report.save(update_fields=['result'])
        publish(batch, self.user)
        delivery = batch.deliveries.get(email='parent-001@example.test')
        with patch('gyanbuddy_insights.tasks.EmailMultiAlternatives.send') as sender:
            send_delivery(str(delivery.pk))
            sender.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'blocked')
        self.assertEqual(delivery.error_code, 'UnsupportedRecommendation')

    def test_smtp_timeout_is_not_automatically_retried(self):
        batch = self.ready()
        publish(batch, self.user)
        delivery = batch.deliveries.first()
        with patch('gyanbuddy_insights.tasks.EmailMultiAlternatives.send', side_effect=TimeoutError) as sender:
            send_delivery(str(delivery.pk))
            send_delivery(str(delivery.pk))
        self.assertEqual(sender.call_count, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'uncertain')

    def test_interrupted_smtp_claim_becomes_uncertain(self):
        batch = self.ready()
        publish(batch, self.user)
        delivery = batch.deliveries.first()
        EmailDelivery.objects.filter(pk=delivery.pk).update(state='sending', locked_until=timezone.now() - timedelta(seconds=1))
        with patch('gyanbuddy_insights.tasks.send_delivery.delay'), patch('gyanbuddy_insights.tasks.generate_student.delay'):
            dispatch_pending()
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'uncertain')

    def test_generation_retry_and_expired_claim(self):
        report = self.batch().reports.first()
        with patch('gyanbuddy_insights.generation.generate', side_effect=RuntimeError):
            generate_student(str(report.pk))
        report.refresh_from_db()
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.attempts, 1)
        StudentReport.objects.filter(pk=report.pk).update(state='processing', locked_until=timezone.now() - timedelta(seconds=1))
        generate_student(str(report.pk))
        report.refresh_from_db()
        self.assertEqual(report.state, 'ready')
        self.assertEqual(report.attempts, 2)

    def test_expired_last_generation_attempt_terminates(self):
        report = self.batch().reports.first()
        StudentReport.objects.filter(pk=report.pk).update(state='processing', attempts=3, locked_until=timezone.now() - timedelta(seconds=1))
        with patch('gyanbuddy_insights.tasks.generate_student.delay'):
            dispatch_pending()
        report.refresh_from_db()
        self.assertEqual(report.state, 'failed')

    def test_rollback_removes_jobs(self):
        try:
            with transaction.atomic():
                self.batch()
                raise ValueError('marks save failed')
        except ValueError:
            pass
        self.assertEqual(Batch.objects.count(), 0)

    def test_html_escapes_uploaded_text(self):
        data = payload()
        data['records'][0]['student_name'] = '<script>bad()</script>'
        batch = submit_marks(school_id='school-a', payload=data)[0]
        for r in batch.reports.all():
            generate_student(str(r.pk))
        publish(batch, self.user)
        send_delivery(str(batch.deliveries.get(email='parent-001@example.test').pk))
        self.assertNotIn('<script>', mail.outbox[0].alternatives[0].content)

    @override_settings(INSIGHTS_PROVIDER='gemini', INSIGHTS_GEMINI_MODEL='')
    def test_missing_cloud_configuration_never_silently_sends_rules(self):
        report = self.batch().reports.first()
        generate_student(str(report.pk))
        report.refresh_from_db()
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.result, {})
