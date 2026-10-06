import uuid
from django.db import models


class Batch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_id = models.CharField(max_length=100, db_index=True)
    event_id = models.CharField(max_length=150)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.CharField(max_length=150, blank=True)
    send_requested_at = models.DateTimeField(null=True, blank=True)
    send_requested_by = models.CharField(max_length=150, blank=True)
    publication_error = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school_id", "event_id"], name="insight_unique_event")]


class StudentReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="reports")
    student_id = models.CharField(max_length=100)
    records = models.JSONField()
    result = models.JSONField(default=dict)
    state = models.CharField(max_length=20, default="queued", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    claim = models.UUIDField(null=True)
    available_at = models.DateTimeField(null=True)
    locked_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "student_id"], name="insight_unique_student")]


class EmailDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="deliveries")
    email = models.EmailField()
    role = models.CharField(max_length=20)
    student_ids = models.JSONField()
    # pending -> sending -> sent; uncertain SMTP outcomes require reconciliation.
    state = models.CharField(max_length=20, default="pending", db_index=True)
    claim = models.UUIDField(null=True)
    locked_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    sent_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "email", "role"], name="insight_unique_email")]


class DeliveryResolution(models.Model):
    delivery = models.ForeignKey(EmailDelivery, on_delete=models.CASCADE, related_name="resolutions")
    action = models.CharField(max_length=20)
    operator = models.CharField(max_length=150)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
