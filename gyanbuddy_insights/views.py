from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404
from pydantic import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.decorators import renderer_classes
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as APIValidationError
from .access import management_scope
from .models import Batch
from .services import submit_marks, request_send, recipient_plan, email_all_from_database
from .schema import DatabaseSendRequest


def scoped_batch(request, batch_id):
    return get_object_or_404(Batch, pk=batch_id, school_id=management_scope(request.user))


def summary(batch):
    states = dict(batch.reports.values("state").annotate(n=Count("id")).values_list("state", "n"))
    total = sum(states.values())
    ready = states.get("ready", 0)
    return {
        "id": str(batch.id), "event_id": batch.event_id,
        "status": "published" if batch.published_at else ("ready" if ready == total and total else "failed" if states.get("failed") else "processing"),
        "total_students": total, "ready_students": ready, "report_states": states,
        "email_states": dict(batch.deliveries.values("state").annotate(n=Count("id")).values_list("state", "n")),
        "published_at": batch.published_at,
        "created_at": batch.created_at,
        "send_requested_at": batch.send_requested_at,
        "publication_error": batch.publication_error,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def marks_uploaded(request):
    try:
        batch, created = submit_marks(school_id=management_scope(request.user), payload=request.data)
    except ValidationError as exc:
        raise APIValidationError(exc.errors(include_url=False, include_context=False, include_input=False))
    except DjangoValidationError as exc:
        raise APIValidationError(exc.messages)
    return Response(summary(batch), status=202 if created else 200)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def email_all_reports(request):
    school = management_scope(request.user)
    try:
        data = DatabaseSendRequest.model_validate(request.data)
        batch, created = email_all_from_database(school_id=school, reporting_id=data.reporting_id, user=request.user)
    except ValidationError as exc:
        raise APIValidationError(exc.errors(include_url=False, include_context=False, include_input=False))
    except DjangoValidationError as exc:
        raise APIValidationError(exc.messages)
    return Response({**summary(batch), "newly_requested": created}, status=202 if created else 200)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def batch_status(request, batch_id):
    return Response(summary(scoped_batch(request, batch_id)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def batches(request):
    school = management_scope(request.user)
    offset = page_offset(request)
    items = Batch.objects.filter(school_id=school).order_by("-created_at", "-id")
    return Response({"count": items.count(), "results": [summary(b) for b in items[offset:offset + 20]]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_config(request):
    management_scope(request.user)
    return Response({"mode": "django", "can_generate": False, "can_send": True,
                     "description": "Connected to Django · reports and email status for your school."})


@api_view(["GET"])
@renderer_classes([TemplateHTMLRenderer])
@permission_classes([IsAuthenticated])
def dashboard(request):
    management_scope(request.user)
    return Response({}, template_name="gyanbuddy_insights/dashboard.html")


def page_offset(request):
    try:
        offset = int(request.query_params.get("offset", 0))
        if offset < 0:
            raise ValueError
        return offset
    except ValueError:
        raise APIValidationError("offset must be a non-negative integer")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports(request, batch_id):
    batch = scoped_batch(request, batch_id)
    offset = page_offset(request)
    items = batch.reports.order_by("student_id")
    return Response({"count": items.count(), "results": [
        {"student_id": r.student_id, "student_name": r.records[0]["student_name"], "state": r.state, "error_code": r.error_code, "report": r.result}
        for r in items[offset:offset + 50]
    ]})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def emails(request, batch_id):
    batch = scoped_batch(request, batch_id)
    try:
        if request.method == "POST":
            batch, created = request_send(batch, request.user)
            return Response({**summary(batch), "newly_queued": created}, status=202 if created else 200)
        offset = page_offset(request)
        if not batch.published_at:
            plan = recipient_plan(batch)
            return Response({"count": len(plan), "results": plan[offset:offset + 50]})
        items = batch.deliveries.order_by("email", "role")
        return Response({"count": items.count(), "results": list(items.values(
            "id", "email", "role", "student_ids", "state", "error_code", "sent_at"
        )[offset:offset + 50])})
    except DjangoValidationError as exc:
        raise APIValidationError(exc.messages)
