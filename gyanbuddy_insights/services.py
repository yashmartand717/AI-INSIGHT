import hashlib
import json
from collections import defaultdict
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from .access import adapter
from .models import Batch, StudentReport, EmailDelivery
from .schema import Submission

ROLES = {"parent", "teacher", "principal"}


class Conflict(APIException):
    status_code = 409
    default_detail = "Report operation conflicts with its current state"


def wake_worker():
    # Database rows are the durable queue. Beat recovers broker outages.
    if getattr(settings, "INSIGHTS_KICK_ON_COMMIT", False):
        from .tasks import dispatch_pending
        transaction.on_commit(lambda: dispatch_pending.delay(), robust=True)


def submit_marks(*, school_id, payload):
    """Call inside the marks-save transaction with authoritative data from Django."""
    school_id = str(school_id)
    if not school_id or len(school_id) > 100:
        raise ValidationError("A valid school_id is required")
    submission = Submission.model_validate(payload)
    normalized = submission.model_dump(mode="json")
    normalized["records"].sort(key=lambda r: r["record_id"])
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    adapter().validate_records(school_id, normalized["records"])
    grouped = defaultdict(list)
    for row in normalized["records"]:
        grouped[row["student_id"]].append(row)
    if any(len(rows) > 200 for rows in grouped.values()):
        raise ValidationError("Submit at most 200 test records per student in a reporting snapshot")
    with transaction.atomic():
        batch, created = Batch.objects.get_or_create(
            school_id=school_id, event_id=submission.event_id,
            defaults={"payload_hash": digest},
        )
        if batch.payload_hash != digest:
            raise Conflict("This event_id already exists with different marks. Use a new revision event_id.")
        if created:
            StudentReport.objects.bulk_create([
                StudentReport(batch=batch, student_id=sid, records=rows) for sid, rows in grouped.items()
            ])
        wake_worker()
    return batch, created


def recipient_plan(batch):
    students = set(batch.reports.values_list("student_id", flat=True))
    result = defaultdict(set)
    covered = {role: set() for role in ROLES}
    for item in adapter().recipients(batch.school_id, sorted(students)):
        email = str(item["email"]).strip().lower()
        validate_email(email)
        role = item["role"]
        ids = set(map(str, item["student_ids"]))
        if role not in ROLES or not ids or not ids <= students:
            raise ValidationError("Recipient mapping contains an invalid role or unrelated student")
        result[(email, role)].update(ids)
        covered[role].update(ids)
    missing = {role: sorted(students - ids) for role, ids in covered.items() if students - ids}
    if missing:
        raise Conflict({"message": "Some students are missing verified email recipients", "missing": missing})
    return [{"email": email, "role": role, "student_ids": sorted(ids)} for (email, role), ids in sorted(result.items())]


def publish(batch, user):
    """One click creates a transactional, deduplicated email outbox."""
    with transaction.atomic():
        batch = Batch.objects.select_for_update().get(pk=batch.pk)
        if batch.published_at:
            return batch, False
        if not batch.reports.exists() or batch.reports.exclude(state="ready").exists():
            raise Conflict("Wait until every student report is ready before sending")
        plan = recipient_plan(batch)
        EmailDelivery.objects.bulk_create([EmailDelivery(batch=batch, **item) for item in plan])
        batch.published_at = timezone.now()
        batch.published_by = str(user.pk)
        batch.save(update_fields=["published_at", "published_by"])
        wake_worker()
    return batch, True
