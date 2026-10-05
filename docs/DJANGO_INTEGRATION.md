# GyanBuddy email insights integration

## What is ready

An installable Django app, migrations, background generation and email delivery tasks, authenticated REST endpoints, HTML/plain-text email templates, recovery commands, and a Flutter send button example.

The actual GyanBuddy backend is not in this workspace. Its student relationships, authentication configuration, production database, Gemini settings and SMTP account still need to be connected. The existing FastAPI dashboard is a separate local preview; uploading a CSV there does not enqueue Django emails.

## Workflow

1. GyanBuddy saves marks and calls `submit_marks()` in the same database transaction.
2. The module stores an immutable reporting snapshot and one generation job per student.
3. Celery workers calculate metrics, then make one Gemini request per student for parent, teacher and principal versions.
4. Flutter polls batch progress. A school administrator can review reports and recipients.
5. **Email all reports** creates a durable email outbox. Parents receive only their linked children; staff receive combined emails for the students they are authorized to see.
6. Workers recheck relationships and send through Django's configured mail backend. Delivery states remain available through the API.

The principal summary describes the students included in this batch, not the entire school unless that batch includes the entire school. Parent, teacher and principal emails are separate, even if someone has multiple roles. No CC/BCC exposes other recipients.

## Install in the Django backend

Use Python 3.11+ with Django 5.2. Review dependency compatibility if the host runs another Django version.

```bash
pip install /path/to/AI-INSIGHT
python manage.py migrate gyanbuddy_insights
```

Add the apps before running migrations:

```python
INSTALLED_APPS += ["rest_framework", "gyanbuddy_insights"]
```

If DRF is already installed, don't add it twice. Ensure the project has Django templates configured with `APP_DIRS=True`. Use PostgreSQL for deployment; tests use SQLite and do not establish PostgreSQL concurrent behavior.

In the host URL configuration:

```python
from django.urls import include, path

urlpatterns += [path("api/insights/", include("gyanbuddy_insights.urls"))]
```

The endpoints use the host's `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`. Keep GyanBuddy's existing JWT/token authentication. All endpoints require authentication and the adapter's school-management permission. Do not put SMTP passwords or Gemini keys in Flutter.

## Connect real users and student relationships

Set `INSIGHTS_ACCESS_ADAPTER = "your_app.insights_access.GyanBuddyAccess"`. Implement a subclass of `gyanbuddy_insights.access.AccessAdapter` using the real models. The default denies access.

| Method | Required behavior |
| --- | --- |
| `school_for(user)` | Return an authorized school ID from the authenticated user's current membership. Never trust a request-body school ID. |
| `can_manage(user, school_id)` | Verify a permission to manage and email these reports. A parent or ordinary student must return false. |
| `validate_records(school_id, records)` | Verify every student belongs to that school and names/classes/subjects match authoritative data. Raise `PermissionDenied` for unrelated data. |
| `recipients(school_id, student_ids)` | Query verified, active parent/teacher/principal relationships and return only authorized addresses and requested student IDs. Respect email preferences. |

Return this shape from `recipients()` (illustrative test addresses only):

```python
[
    {"email": "parent@example.test", "role": "parent", "student_ids": ["001"]},
    {"email": "teacher@example.test", "role": "teacher", "student_ids": ["001", "002"]},
    {"email": "principal@example.test", "role": "principal", "student_ids": ["001", "002"]},
]
```

Add the parent mapping for `002` as well; publication requires coverage for every student in all three roles. A missing recipient blocks the whole send action with details so the developer can correct the relationship. Multiple parents and multiple teachers are supported. Duplicate email/role entries are merged.

The adapter must authorize access to **all records in each student's snapshot**. If a subject teacher is allowed to see only one subject, submit a subject-scoped batch or implement a separate scoped reporting policy; do not map that teacher to a cross-subject snapshot. Fetch relationships in bulk. `recipients()` is called again just before sending; it must also work with a subset of the original student IDs.

`integration_tests/test_integration.py` contains an executable fixture adapter; it is for tests only and must not be used in production.

## Automatically trigger after marks upload

Integrate in the existing Django marks-save service, after its normal authorization and validation:

```python
from django.db import transaction
from gyanbuddy_insights.services import submit_marks

with transaction.atomic():
    # Run your existing marks persistence here.
    # Build reporting_records from the newly saved authoritative Django marks.
    batch, created = submit_marks(
        school_id=str(school.pk),
        payload={
            "event_id": f"marks-upload:{upload.pk}:revision:{upload.revision}",
            "records": reporting_records,
        },
    )
    # Persist batch.id with your upload so Flutter can reopen progress later.

# Include str(batch.id) as insight_batch_id in the existing upload response.
```

`submit_marks()` adds database rows only by default; it makes no AI, SMTP or broker call in the upload request. Rollback of the surrounding transaction also removes the jobs. The periodic dispatcher sees committed jobs and wakes the workers. Optional `INSIGHTS_KICK_ON_COMMIT=True` requests an immediate broker wakeup after commit; leave it false to avoid broker latency in requests.

Each snapshot contains the desired reporting period for the affected students. The module does not merge marks across previous uploads automatically. Include historical records or explicit `previous_score_pct` if needed. For corrected marks, submit a new event revision. Replaying the same event with the same data returns the same batch; replaying with changed data returns HTTP 409.

### Normalized record

```json
{
  "record_id": "exam-42:student-001:topic-poetry",
  "student_id": "001",
  "student_name": "Example Student",
  "class_name": "Class 7",
  "section": "B",
  "subject": "English",
  "chapter": "Poetry",
  "subtopic": "Interpreting a poem",
  "total_questions": 20,
  "correct": 12.5,
  "test_date": "2026-10-06"
}
```

`correct` and `total_questions` can represent earned/max marks, including decimals. Keep both in the same unit. Optional `attempted` must use the same unit; omit it for marks data where attempted-question count would mix units. If omitted, the engine assumes the maximum for that internal field, not verified attempt behavior. `record_id` must be unique within a batch; IDs are strings to retain leading zeroes. Maximum: 10,000 records per batch and 200 per student. No fabricated attendance, engagement, gender or improvement is inferred from marks.

## Worker configuration

Use the host's existing Celery app with Django settings and `app.autodiscover_tasks()`. Ensure it is imported from the host project `__init__.py`, as in the [Celery Django setup](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html).

```python
CELERY_BROKER_URL = os.environ["CELERY_BROKER_URL"]
CELERY_TASK_ROUTES = {"gyanbuddy_insights.tasks.*": {"queue": "insights"}}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {
    # Merge with existing schedules rather than replacing them.
    "insights-dispatch": {
        "task": "gyanbuddy_insights.tasks.dispatch_pending",
        "schedule": 10.0,
    },
}
```

Run a dedicated worker and one Beat scheduler (deployment on Linux recommended):

```bash
celery -A your_project worker -Q insights --concurrency=2 --loglevel=INFO
celery -A your_project beat --loglevel=INFO
```

Keep Beat running: database jobs survive broker outages, but require the dispatcher to resume. Generation gets up to three attempts with increasing delays. Claims prevent duplicate task messages from writing or sending twice. The dispatcher recovers expired generation claims. Tune concurrency to the actual model and mail-provider quotas; no CPU or cost guarantees are assumed. Bound provider timeouts below the 10-minute claim duration.

## Gemini configuration

```python
INSIGHTS_PROVIDER = "gemini"
INSIGHTS_GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
INSIGHTS_GEMINI_MODEL = os.environ["GEMINI_MODEL"]  # enabled model in your account
```

The module uses structured JSON output and validates all three role versions with Pydantic. It removes the explicit student name, ID, roll number and section fields before the cloud request; free-text fields may still contain personal information, so normalize them in the host. Calculated metrics stay authoritative. Schema validation does not establish factual correctness of generated prose; review representative live outputs before release.

Use `INSIGHTS_PROVIDER="rules"` for explicit offline development. Those emails are labelled rule-based. AI failures never silently convert to rule-based output. No live Gemini request was made during implementation testing. See [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

## Email configuration

Start in a staging environment using Django's console or file mail backend. For SMTP:

```python
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ["EMAIL_HOST"]
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ["EMAIL_HOST_USER"]
EMAIL_HOST_PASSWORD = os.environ["EMAIL_HOST_PASSWORD"]
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = os.environ["DEFAULT_FROM_EMAIL"]
INSIGHTS_MESSAGE_ID_DOMAIN = os.environ["INSIGHTS_MESSAGE_ID_DOMAIN"]
```

Use a verified sending domain configured with your mail provider. If it requires implicit SSL, use port 465 with `EMAIL_USE_SSL=True` and `EMAIL_USE_TLS=False`. Keep credentials in server environment variables. See [Django email configuration](https://docs.djangoproject.com/en/5.2/topics/email/).

States: `pending`, `sending`, `sent`, `blocked`, `uncertain`. **Sent means the configured email backend accepted the message**, not that it reached the recipient's inbox. Provider delivery/bounce webhooks are not implemented. Large teacher/principal digests may need pagination or a private report link at production scale; email HTML includes full text, not PDF attachments.

A timeout may occur after SMTP accepted a message. Such deliveries become `uncertain` and are not automatically resent. Check provider logs using the stable Message-ID before reconciling. Repeated send-button clicks do not create new outbox rows, but SMTP does not provide an exactly-once guarantee.

```bash
python manage.py insights_retry_batch BATCH_UUID
python manage.py insights_resolve_email DELIVERY_UUID --action mark-sent --operator OPERATOR_ID --reason "Acceptance verified in provider logs"
python manage.py insights_resolve_email DELIVERY_UUID --action retry --confirmed-not-sent --operator OPERATOR_ID --reason "Provider confirms no accepted message"
```

These operator commands require trusted server access. Reconciliation is recorded in `DeliveryResolution`. A retried email rechecks relationships. Retain reports, delivery logs and snapshots according to GyanBuddy's data policy.

## REST contract

All paths below are relative to `/api/insights/`. The school comes from the authenticated user, never from the payload. Flutter never supplies recipient addresses.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `marks-uploaded/` | Optional integration endpoint accepting `{event_id, records}`; prefer the transaction hook when marks are saved in the same backend. |
| GET | `batches/{id}/` | Generation counts, overall state and email counts. |
| GET | `batches/{id}/reports/?offset=0` | Up to 50 student reports for authorized administrator preview. |
| GET | `batches/{id}/emails/?offset=0` | Recipient plan before sending; delivery log after sending. Up to 50 rows. |
| POST | `batches/{id}/emails/` | One-click publication. Empty JSON body. Returns 202 first time, 200 if already published. |

Validation errors: 400. Missing authentication: 401/403 according to host auth. Forbidden management access: 403. Cross-school or unknown batch: 404. Reports not ready, event mismatch or missing recipients: 409.

Status example:

```json
{"id":"BATCH_UUID","event_id":"upload-42:r1","status":"ready","total_students":30,"ready_students":30,"report_states":{"ready":30},"email_states":{},"published_at":null}
```

The report API returns `metrics`, `insights.parent`, `insights.teacher`, `insights.principal`, `source` and `model` under each result's `report`. This is an administrator endpoint, not a parent-facing read API.

## Flutter

Copy `flutter_example/insight_email_panel.dart` into the existing app and add the `http` dependency if needed. Pass the app's authenticated HTTP client and the batch ID returned by marks upload:

```dart
InsightEmailPanel(
  batchId: uploadResponse.insightBatchId,
  api: InsightsApi(Uri.parse('$apiOrigin/api/insights/'), authenticatedClient),
)
```

The base URL must end with `/`. The widget polls status and enables **Email all reports** when generation completes. A lost publish response can be retried safely: the same batch does not create a second outbox. Configure the authenticated client to include the existing app token. The example has not been compiled: Flutter/Dart SDKs are not installed in this workspace.

## Verification and deployment boundary

Run `python -m django test integration_tests --settings=integration_tests.settings` from the source checkout after installing integration dependencies. Tests use memory email and an isolated database, never real recipients. Covered: creation, generation, grouped email contents, repeat events/clicks/tasks, invalid marks, tenant isolation, authentication, missing/changed recipients, rollback, retries, interrupted workers, SMTP uncertainty and HTML escaping.

Before connecting real school data, complete the adapter and exercise the host authentication, PostgreSQL concurrency, Redis/Celery workers, chosen Gemini model and staging SMTP. This source package is ready for that integration work; it is not already installed in the live GyanBuddy backend.
