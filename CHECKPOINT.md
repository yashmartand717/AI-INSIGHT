# AI Insight Engine checkpoint

Updated: 6 October 2026

## Product constraint: no recorded lectures

GyanBuddy has no recorded lectures. All report prompts now state this explicitly and suggest textbooks, written practice, review of mistakes and teacher discussion. Shared output validation rejects recorded/video lesson recommendations in generated prose. Django generation and email preparation both enforce the guard, including saved reports queued before this correction. A blocked saved report should be regenerated using a new batch revision; existing history is not rewritten.

## Progress GUI added

- Local dashboard: `http://localhost:8000/progress`, linked from the report dashboard navigation.
- Shared standalone HTML/CSS/JS dashboard ships in the Django package at `/api/insights/dashboard/` with authenticated school-scoped history and configuration endpoints.
- Automatic polling, batch selection and pagination, report progress, per-student status, parent/teacher/principal report previews, recipient lists and email status counters. Django mode includes the one-click publication action.
- Local mode runs real offline analysis of the uploaded data and keeps batch history in ignored SQLite storage. Local email is explicitly disconnected and cannot send. Interrupted local batches are marked for attention on restart.
- Browser automation was blocked by the browser policy; visual layout verification remains pending. All 37 tests pass (16 local/API tests and 21 Django tests), and JavaScript syntax is valid. The local app has been restarted with the progress routes. These changes are local until the next GitHub push.

## Django + Flutter email integration added

User chose email delivery. Built `gyanbuddy_insights`, an installable Django 5.2 app with migrations, database-backed generation jobs, Celery tasks, a transactional email outbox, role-specific templates, tenant-scoped authenticated API endpoints, recovery commands and an audit record for manual delivery reconciliation. One Gemini call produces three report variants per student; offline mode is explicit and labelled. Send publication groups reports by recipient and role. Relationships are resolved in the host adapter and checked again before transmission. Repeated event IDs and send clicks are idempotent.

`docs/DJANGO_INTEGRATION.md` is the developer guide. `flutter_example/insight_email_panel.dart` contains the one-click email UI. `scripts/build_integration_package.py` builds the handoff ZIP. The existing preview has an Email Integration tab linking to both.

Verification: 20 Django integration tests and the 10 existing regression tests pass. Integration tests use an isolated database and in-memory mail; no real emails or live AI requests have been made. The distributable wheel builds successfully, Django checks pass, and migrations are current. Flutter/Dart is not installed, so the widget has not been compiled. A separate `.venv-integration` contains dependencies for these tests. The host Django backend source was not supplied. Its access adapter, marks-upload hook, authentication, PostgreSQL deployment, Redis/Celery, SMTP credentials and selected Gemini model must still be wired and tested. SMTP acceptance is recorded as sent; actual inbox delivery/bounce tracking is not implemented. The old standalone FastAPI dashboard remains a demo and is not the production integration API.

Next priority for integration: obtain the GyanBuddy backend path and implement the real model mapping described in the guide, then run staging delivery through its configured email account.

## Completed this session

- Fixed the upload-to-report flow: parent selection uses the current roster, and teacher selection uses uploaded class/section/subject groups from `/api/report-groups`.
- Principal scores and bottleneck averages come from calculated metrics rather than fixed sample percentages.
- Import validation rejects missing required fields, non-finite or inconsistent scores and conflicting student IDs before writing data. Existing data and report cache survive validation failures.
- Decimal scores and leading-zero text IDs survive parsing. Generated IDs group repeated tests by class/section plus roll number or name. Namesake ambiguity is shown as a warning.
- Missing class, section, subject and chapter values are explicitly unspecified; missing test dates remain blank. Missing historical scores produce no invented progress delta.
- Offline parent, teacher and principal report text uses actual records. Removed invented teacher names, peer pairs, schedules, gender and sample-topic claims. Healthy records do not create fake bottlenecks.
- Report views clear old values and show request failures. Request counters prevent older responses from overwriting newer report selections. Uploaded labels rendered into the parent table are HTML-escaped.
- Added upload dependencies (`python-multipart`, `openpyxl`, `xlrd`) and a test dependency file.
- Uploads are rejected while the batch worker reports that it is running.

## Verification

- Ten unittest regressions pass. They cover import validation, preservation of existing data/cache on invalid imports, repeated students, decimals, leading-zero IDs, roll-number scoping, conflicting IDs, unknown metadata, revision focus, healthy results and batch/upload exclusion.
- Tests use a disposable directory and force offline reports. Existing user data was not replaced, and cloud generation was not called.
- The Excel parser route was tested with a mocked parser result. A real Excel workbook round-trip remains unverified.
- Python compilation and JavaScript syntax checks pass.
- Visual browser verification was blocked by the browser permission setting. Do not claim the changed UI was visually tested.

## Next work

1. Verify the upload, class selector, switching students and all three reports in an allowed browser. Include loading/error states and a real Excel upload in a disposable test environment.
2. Review provider configuration and validate configured Gemini model IDs against official documentation. Model IDs and source labels currently disagree. Make fallback use visible per report and validate generated report schemas. Live AI was not checked in this session.
3. Verify token pricing and cost assumptions. README and UI still contain historical cost and CPU claims that have not been measured or revalidated.
4. Repair batch execution: the current loop is sequential despite a semaphore, cache entries are keyed only by student ID, error results can be cached and progress does not include failures. Address dataset consistency and concurrent job startup before enabling larger runs.
5. Repeated-result aggregation now weights all supplied rows by available credit. Teacher chapter counts use unique students; principal critical-gap percentages use each student's aggregate subject score. These are cumulative uploaded results, not latest-test trends.
6. Harden persistence for interrupted writes and concurrent uploads. Current import validation protects against invalid files, but writing JSON and CSV is not transactional.

## Local commands

- Run application: `python app.py`
- Install runtime: `python -m pip install -r requirements.txt`
- Install test dependencies: `python -m pip install -r requirements-dev.txt`
- Regression checks: `python -m unittest discover -s tests -v`
- JavaScript syntax: `node --check static/js/app.js`

This directory is a Git repository on `main`, with origin `https://github.com/yashmartand717/AI-INSIGHT.git`. Preserve `.env` and existing data. Credentials, local student data and Excel files are excluded from Git. Scratch scripts under `.system_generated` are support files, not part of the application.

## Report quality corrections — 2026-10-06

- Parent, teacher and principal student reports explain earned/available scores, give constructive evidence-based wording, three audience-specific actions, a follow-up check and explicit evidence limits. No recorded-lecture recommendations.
- Repeated topics are weighted once for strengths/priorities; class counts and principal percentages count unique students. Row-level submitted results remain available.
- Dashboard and HTML/plain-text emails display follow-up and evidence sections. Legacy parent reports share the same builder; class/school summaries and all cloud prompts have corresponding guidance.
- Local ready rule-based previews upgrade from their saved marks at startup, with a SQLite backup before changes. Existing batch IDs and source records are preserved. This does not rewrite published Django reports or resend emails.
- Report version invalidates older standalone cached reports. Cloud generation has not been tested live.

Verification: 29 standalone tests and 22 Django integration tests pass (51 total), including email text/HTML content, weighted repeated results and saved-report upgrades. Both dashboard scripts pass syntax checks. All 8 saved local student reports (24 audience versions) were refreshed from snapshots with a database backup. Live dashboard/API checks passed on localhost:8000; Kavita's corrected report was confirmed through the reports endpoint. ZIP and wheel rebuilt. Browser visual verification and live cloud generation remain unverified. Current local server PID: 37932.

## OpenAI integration — 2026-10-06

OpenAI now generates all three role reports in one structured Responses API request in the Django worker and local progress workflow. Select INSIGHTS_PROVIDER=openai with server-side OPENAI_API_KEY and OPENAI_MODEL (default gpt-4o-mini). Django accepts INSIGHTS_OPENAI_API_KEY and INSIGHTS_OPENAI_MODEL settings. Keys are not exposed by config endpoints. Model input omits explicit identity fields. Provider refusals, incomplete output, invalid schema and forbidden recommendations fail; the durable Django queue handles retries. The SDK uses 60-second timeout, max_retries=0 and store=False. Cloud schema requires follow-up/evidence sections and exactly three actions. Reports and emails label OpenAI sources. Existing offline previews are preserved; use Analyse uploaded marks for a new AI batch. New SDK dependency is included in integration requirements and packaging. Legacy standalone report provider selection also respects explicit OpenAI configuration.

OpenAI verification: 31 standalone and 31 Django tests pass (62 total). Tests use mocked provider responses and cover source routing, all audience outputs, identity omission, no key exposure, strict SDK schema, refusals/incomplete output, API failures, configuration, report queue and email delivery labels. JavaScript syntax passes. ZIP and wheel rebuilt. No live cloud requests were made. Dashboard HTTP/config checks pass; restarted local server PID 3764.

## Database-driven one-click Gmail delivery — 2026-10-06

- Added AccessAdapter.marks_for_report(school_id, reporting_id) and authenticated POST email-all-reports/. The host adapter queries authoritative marks and linked recipient addresses; the client supplies only a reporting reference. The actual GyanBuddy schema is not available here, so the host must implement these methods using its real models.
- Identical database snapshots reuse a batch; changed marks produce a new snapshot. Missing recipients roll back initial requests. Batch send intent is durable and generation/periodic dispatcher automatically publishes when all student reports are ready. Duplicate clicks do not create another outbox. Recipient failures during publication are visible and retryable after mapping correction. Relationships are checked before each send.
- Added migration 0003 for send intent and publication errors. Apply migrations on upgrade. Existing published reports/deliveries are preserved.
- Added optional Gmail SMTP settings helper (STARTTLS port 587, app password from server environment, 30-second timeout). No recipient passwords or inbox access are needed. Gmail account quotas apply; developer guide includes Google references and Workspace/relay alternatives.
- Updated Flutter API with analyseAndSend(reportingId), existing send panel, shared progress dashboard, developer guide, README and environment example. Retrying failed generation resumes a previously requested send.
- Verification: 40 Django tests + 31 standalone tests pass (71 total). One-click end-to-end generation/outbox/memory delivery, repeated clicks, changed marks, tenant rejection, no client recipient overrides, missing/changed recipients, failure recovery and dispatcher recovery are covered. Gmail SMTP transport was mocked; TLS/login/single-recipient routing checked without sending actual mail. Migration drift check and dashboard JavaScript syntax pass. Real GyanBuddy integration, Gmail delivery, Flutter compilation and PostgreSQL concurrency remain unverified.
