"""Durable database queue with Celery wakeups and expiring generation claims."""
import uuid
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.module_loading import import_string
from .access import adapter
from .models import Batch, StudentReport, EmailDelivery
from .schema import InsightBundle
from engine.product_rules import validate_recommendations


@shared_task(ignore_result=True)
def dispatch_pending():
    now = timezone.now()
    eligible = Q(state="queued") & (Q(available_at__isnull=True) | Q(available_at__lte=now))
    eligible |= Q(state="processing", locked_until__lt=now)
    # Expired final attempts must terminate rather than stay processing forever.
    StudentReport.objects.filter(eligible, attempts__gte=3).update(state="failed", error_code="AttemptsExhausted")
    for pk in StudentReport.objects.filter(eligible, attempts__lt=3).values_list("pk", flat=True)[:500]:
        generate_student.delay(str(pk))
    for pk in Batch.objects.filter(send_requested_at__isnull=False, published_at__isnull=True, publication_error="").values_list("pk", flat=True)[:500]:
        finalize_requested_batch(str(pk))
    # SMTP may have accepted a message before a worker died. Never auto-resend it.
    EmailDelivery.objects.filter(state="sending", locked_until__lt=now).update(state="uncertain", error_code="WorkerInterrupted")
    for pk in EmailDelivery.objects.filter(state="pending").values_list("pk", flat=True)[:500]:
        send_delivery.delay(str(pk))


@shared_task(ignore_result=True, acks_late=True)
def generate_student(report_id):
    now = timezone.now()
    claim = uuid.uuid4()
    eligible = Q(state="queued") & (Q(available_at__isnull=True) | Q(available_at__lte=now))
    eligible |= Q(state="processing", locked_until__lt=now)
    owned = StudentReport.objects.filter(pk=report_id).filter(eligible).filter(attempts__lt=3)
    if not owned.update(state="processing", claim=claim, locked_until=now + timedelta(minutes=10), attempts=F("attempts") + 1):
        return
    report = StudentReport.objects.get(pk=report_id)
    owned = StudentReport.objects.filter(pk=report_id, claim=claim, state="processing")
    try:
        builder = import_string(getattr(settings, "INSIGHTS_GENERATOR", "gyanbuddy_insights.generation.generate"))
        result = builder(report.records)
        InsightBundle.model_validate(result["insights"])
        validate_recommendations(result["insights"])
        # Metrics are always calculated locally, including for custom generators.
        from engine.analytics import analyze_student
        result["metrics"] = analyze_student(report.student_id, report.records)
        if result.get("source") not in ("gemini", "openai", "rules"):
            raise ValueError("Generator must report its source")
        owned.update(state="ready", result=result, error_code="", locked_until=None)
    except Exception as exc:
        owned.update(
            state="failed" if report.attempts >= 3 else "queued",
            error_code=type(exc).__name__, locked_until=None,
            available_at=timezone.now() + timedelta(minutes=report.attempts),
        )
    else:
        finalize_requested_batch(str(report.batch_id))


def finalize_requested_batch(batch_id):
    """Publish only after all reports succeed; Beat recovers interrupted finalization."""
    from types import SimpleNamespace
    from .services import publish
    batch = Batch.objects.get(pk=batch_id)
    if not batch.send_requested_at or batch.published_at or batch.publication_error:
        return
    if not batch.reports.exists() or batch.reports.exclude(state="ready").exists():
        return
    try:
        publish(batch, SimpleNamespace(pk=batch.send_requested_by))
    except Exception as exc:
        Batch.objects.filter(pk=batch_id, published_at__isnull=True).update(publication_error=type(exc).__name__)


def email_context(delivery):
    # Re-check relationships immediately before email transmission.
    allowed = set()
    for item in adapter().recipients(delivery.batch.school_id, delivery.student_ids):
        if str(item["email"]).strip().lower() == delivery.email and item["role"] == delivery.role:
            allowed.update(map(str, item["student_ids"]))
    if not set(delivery.student_ids) <= allowed:
        raise PermissionError("Recipient relationship changed")
    reports = list(delivery.batch.reports.filter(student_id__in=delivery.student_ids, state="ready"))
    if len(reports) != len(delivery.student_ids):
        raise ValueError("A report is missing")
    items = [{"student_id": r.student_id, "metrics": r.result["metrics"],
              "insight": r.result["insights"][delivery.role], "source": r.result["source"]} for r in reports]
    for item in items:
        validate_recommendations(item["insight"])
    total = sum(row["total_questions"] for r in reports for row in r.records)
    earned = sum(row["correct"] for r in reports for row in r.records)
    return {"role": delivery.role, "items": items, "average": round(earned / total * 100, 1), "batch_id": str(delivery.batch_id)}


@shared_task(ignore_result=True, acks_late=True)
def send_delivery(delivery_id):
    claim = uuid.uuid4()
    if not EmailDelivery.objects.filter(pk=delivery_id, state="pending").update(
        state="sending", claim=claim, locked_until=timezone.now() + timedelta(minutes=10)
    ):
        return
    delivery = EmailDelivery.objects.select_related("batch").get(pk=delivery_id)
    owned = EmailDelivery.objects.filter(pk=delivery_id, claim=claim, state="sending")
    try:
        context = email_context(delivery)
        mail = EmailMultiAlternatives(
            subject=f"GyanBuddy learning reports — {delivery.role.title()}",
            body=render_to_string("gyanbuddy_insights/report.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL, to=[delivery.email],
            headers={"Message-ID": f"<insight-{delivery.id}@{getattr(settings, 'INSIGHTS_MESSAGE_ID_DOMAIN', 'gyanbuddy.invalid')}>"},
        )
        mail.attach_alternative(render_to_string("gyanbuddy_insights/report.html", context), "text/html")
    except Exception as exc:
        owned.update(state="blocked", error_code=type(exc).__name__, locked_until=None)
        return
    try:
        if mail.send(fail_silently=False) != 1:
            raise RuntimeError("SMTP did not confirm acceptance")
        owned.update(state="sent", sent_at=timezone.now(), locked_until=None, error_code="")
    except Exception as exc:
        # Includes timeouts after DATA. A retry could send the same email twice.
        owned.update(state="uncertain", error_code=type(exc).__name__, locked_until=None)
