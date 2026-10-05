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

    def test_incomplete_batch_cannot_send(self):
        batch = self.batch()
        self.assertEqual(self.client.post(f'/batches/{batch.pk}/emails/').status_code, 409)
        self.assertEqual(EmailDelivery.objects.count(), 0)

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
