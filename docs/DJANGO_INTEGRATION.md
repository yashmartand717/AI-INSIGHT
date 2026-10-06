# GyanBuddy email insights integration

## What is ready

An installable Django app, migrations, background generation and email delivery tasks, authenticated REST endpoints, HTML/plain-text email templates, recovery commands, and a Flutter send button example.

The actual GyanBuddy backend is not in this workspace. Its student relationships, authentication configuration, production database, AI provider settings and SMTP account still need to be connected. The existing FastAPI dashboard is a separate local preview; uploading a CSV there does not enqueue Django emails.

## Workflow

### Progress dashboard

The web progress dashboard is available at `/api/insights/dashboard/` after installing this module. It displays recent uploads, generation progress, individual student reports, recipient previews, email queue counts and delivery errors, and polls every three seconds while visible. The authenticated `GET batches/` endpoint lists only batches for the user's school; `GET config/` supplies dashboard capabilities. Batch and detail lists support pagination.

For browser access, include DRF `SessionAuthentication` alongside the host's existing token/JWT authentication and sign in through the host's normal Django login. The page uses same-origin session cookies and the rendered CSRF token for publication. Do not disable CSRF checks or expose access tokens in page URLs. Management permissions apply to the page and every API request.

In the standalone local preview, open `http://localhost:8000/progress`. Click **Analyse uploaded marks** to generate reports from the current local dataset using the configured provider (offline rules, OpenAI or Gemini). Local batch history is saved in `.system_generated/progress.sqlite3`; email requires the Django connection. The local email send button is disabled. This local preview runs as a single server process; use the Django module for deployment.

### Processing and sending

1. GyanBuddy saves marks and calls `submit_marks()` in the same database transaction.
2. The module stores an immutable reporting snapshot and one generation job per student.
3. Celery workers calculate metrics, then make one OpenAI or Gemini request per student for parent, teacher and principal versions.
4. Flutter polls batch progress. A school administrator can review reports and recipients.
5. **Email all reports** records the send request; once all reports are ready it automatically creates a durable email outbox. Parents receive only their linked children; staff receive combined emails for the students they are authorized to see.
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
| `marks_for_report(school_id, reporting_id)` | Query an authorized exam/upload/reporting period and return normalized marks from the host database. Required for the database one-click endpoint. Reject unknown or cross-school references. |
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

## OpenAI or Gemini configuration

GyanBuddy does not offer recorded lectures or video lessons. Prompts explicitly prohibit those recommendations and direct reports toward textbooks, written practice, reviewing test mistakes and teacher support. Generated prose is checked for unsupported lecture-media recommendations; email preparation also checks saved report prose. An affected old report is blocked rather than sent. Create a corrected batch revision to regenerate it.

For OpenAI, configure the Django server and worker environment (never the Flutter app):

```python
INSIGHTS_PROVIDER = "openai"
INSIGHTS_OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
INSIGHTS_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
```

One OpenAI Responses API request returns validated parent, teacher and principal reports for each student. Requests use Structured Outputs, a 60-second timeout, no SDK retries (the durable queue owns retries), and `store=False`. Refusals, incomplete output and invalid reports remain failures, never silently labelled offline successes. Explicit identity fields are omitted from model input. See [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

For Gemini:

```python
INSIGHTS_PROVIDER = "gemini"
INSIGHTS_GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
INSIGHTS_GEMINI_MODEL = os.environ["GEMINI_MODEL"]  # enabled model in your account
```

The module uses structured JSON output and validates all three role versions with Pydantic. It removes the explicit student name, ID, roll number and section fields before the cloud request; free-text fields may still contain personal information, so normalize them in the host. Calculated metrics stay authoritative. Schema validation does not establish factual correctness of generated prose; review representative live outputs before release.

Use `INSIGHTS_PROVIDER="rules"` for explicit offline development. Those emails are labelled rule-based. AI failures never silently convert to rule-based output. Provider tests use mocked responses; no live OpenAI or Gemini request was made during implementation testing. See [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

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
| POST | `batches/{id}/emails/` | Request automatic publication, including while analysis is running. Empty JSON body. Returns 202 on the first request, 200 for repeated requests. |
| POST | `email-all-reports/` | Read marks from the host database, analyse and email in one operation. Body: `{ "reporting_id": "exam-42" }`. No marks or email addresses supplied by Flutter. |

Validation errors: 400. Missing authentication: 401/403 according to host auth. Forbidden management access: 403. Cross-school or unknown batch: 404. Event mismatch or missing recipients: 409. A send click while reports are processing is accepted and persists the intent to email when all reports are ready.

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

The base URL must end with `/`. The widget polls status and accepts **Email all reports** while analysis is still running. The persisted send request triggers publication once every report is ready; no second click is needed. A lost publish response can be retried safely: the same batch does not create a second outbox. Configure the authenticated client to include the existing app token. The example has not been compiled: Flutter/Dart SDKs are not installed in this workspace.

## Verification and deployment boundary

Run `python -m django test integration_tests --settings=integration_tests.settings` from the source checkout after installing integration dependencies. Tests use memory email and an isolated database, never real recipients. Covered: creation, generation, grouped email contents, repeat events/clicks/tasks, invalid marks, tenant isolation, authentication, missing/changed recipients, rollback, retries, interrupted workers, SMTP uncertainty and HTML escaping.

Before connecting real school data, complete the adapter and exercise the host authentication, PostgreSQL concurrency, Redis/Celery workers, chosen AI model and staging SMTP. This source package is ready for that integration work; it is not already installed in the live GyanBuddy backend.

## Local dashboard with OpenAI

In the workspace `.env`, set `INSIGHTS_PROVIDER=openai`, `OPENAI_API_KEY` and optionally `OPENAI_MODEL` (default `gpt-4o-mini`). Restart `python app.py`, open `/progress`, and click **Analyse uploaded marks** to create a new batch. The dashboard shows OpenAI and the model on completed reports. Existing saved reports retain their original source. Failures appear as **Needs attention**; after correcting the key/model/quota, create a new batch.

When no provider is specified, local progress selects OpenAI if its key is present, otherwise offline rules. To use Gemini locally, explicitly set `INSIGHTS_PROVIDER=gemini` and `GEMINI_MODEL`. `INSIGHTS_PROVIDER=rules` always selects offline reports even if keys exist. Django settings take precedence over environment values. Django does not load `.env` automatically; the host application must load it or set server environment variables. Email still requires the Django connection and SMTP configuration.

## One click: database marks to recipient emails

Two integration paths are supported:

1. Existing marks uploads call `submit_marks()` and return a batch ID. Clicking `POST batches/{id}/emails/` records the send request immediately. It is safe to click during analysis; the worker publishes automatically after every report succeeds.
2. For an exam already in GyanBuddy's database, call `POST email-all-reports/` with `{"reporting_id":"exam-42"}`. The module calls `marks_for_report()` to read authoritative marks and `recipients()` to read the linked parent, teacher and principal email addresses. It creates the snapshot, generates all reports and publishes automatically. This is the method to wire to an exam's **Email all reports** button.

The authenticated user's school controls the query. The client cannot override the school, marks or recipients. Identical clicks for the same reporting reference and marks return the same batch, including after publication. Changed marks produce a new snapshot. Missing/invalid recipient mappings reject the initial click and roll back a newly created snapshot. Relationship changes before publication block sending and set `publication_error`; correct the database mappings and repeat the batch send action. Each individual delivery checks relationships again before SMTP.

`send_requested_at` confirms the click was recorded. `published_at` means emails entered the outbox. A failed student report blocks the whole publication; repair/retry generation using `insights_retry_batch`. Keep Celery workers and the documented periodic dispatcher running: they recover processing and finalization after restarts. Tests do not establish concurrent PostgreSQL behavior.

### Example database queries to adapt

The actual GyanBuddy models are not available in this repository. The model and field names below are illustrative; map them to the host schema. Put these methods on the same access adapter that implements school permissions. Do not create duplicate user/email tables in the insight module.

```python
def marks_for_report(self, school_id, reporting_id):
    # Mark is GyanBuddy's own marks model. Verify the exam belongs to school_id.
    rows = Mark.objects.filter(
        exam_id=reporting_id, student__school_id=school_id, exam__school_id=school_id,
    ).select_related("student", "subject", "chapter", "exam").order_by("pk")
    return [{
        "record_id": str(m.pk), "student_id": str(m.student_id),
        "student_name": m.student.full_name, "class_name": m.student.class_name,
        "section": m.student.section, "subject": m.subject.name,
        "chapter": m.chapter.name, "correct": float(m.marks_obtained),
        "total_questions": float(m.maximum_marks), "test_date": m.exam.date.isoformat(),
    } for m in rows]


def recipients(self, school_id, student_ids):
    # RecipientLink represents the host's verified relationships, not a new module table.
    # If parents and staff use different models, query each and build this same shape.
    links = RecipientLink.objects.filter(
        student__school_id=school_id, student_id__in=student_ids,
        active=True, email_reports_enabled=True,
    ).select_related("recipient")
    return [{
        "email": link.recipient.email, "role": link.role,
        "student_ids": [str(link.student_id)],
    } for link in links]
```

Every student needs at least one parent, teacher and principal mapping. Scope teacher access to the entire included snapshot; for subject-only teachers, use a subject-scoped reporting reference. Addresses may be Gmail or any other valid email domain. Recipient passwords and access to their Gmail inboxes are never needed.

Flutter can invoke the new flow from the exam screen:

```dart
final batch = await insightsApi.analyseAndSend(exam.id.toString());
// Show InsightEmailPanel(batchId: batch['id'], api: insightsApi).
// The click already requested sending; the panel displays analysis/delivery progress.
```

### Gmail sender setup

The module uses Django's SMTP backend to send from a school-controlled Gmail/Google Workspace account. Set these secrets in the backend environment:

```dotenv
GMAIL_SENDER_EMAIL=your-school-sending-address
GMAIL_APP_PASSWORD=your-google-app-password
```

In the host Django settings (after loading environment variables):

```python
from gyanbuddy_insights.gmail import gmail_smtp_settings
globals().update(gmail_smtp_settings())
```

The helper configures `smtp.gmail.com`, port 587, STARTTLS, a 30-second timeout and the sender address. Use an app password for the sender account where supported; Google requires 2-Step Verification and some organization policies prevent app passwords. Do not use a normal account password. If app passwords are unavailable, configure an administrator-approved Workspace SMTP relay or a host email backend using OAuth instead; interactive Gmail OAuth is not implemented by this helper. [Google SMTP setup](https://support.google.com/a/answer/176600), [Google app passwords](https://support.google.com/accounts/answer/185833).

Gmail sending quotas still apply. Personal Gmail can block sending above 500 emails per day; it is not suitable for sending 1,500 individual parent reports in a single day. Select a Workspace/SMTP service with enough allowance for the school's actual recipient count and configure worker throughput accordingly. Quota/SMTP errors appear in delivery status; uncertain deliveries require the existing reconciliation process rather than blind resending. [Google sending limits](https://support.google.com/mail/answer/22839).

No real GyanBuddy database, Gmail account or live email has been connected in this workspace. The developer must implement the access adapter, apply migrations, set AI/Gmail credentials, and run the worker/dispatcher in the host project.
