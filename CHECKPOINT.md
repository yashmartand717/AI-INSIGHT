# AI Insight Engine checkpoint

Updated: 6 October 2026

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
5. Review repeated-test aggregation: teacher chapter counts currently count test rows, and the principal field `critical_gap_students_pct` is computed from test rows. Define whether latest tests, all attempts or unique students are intended.
6. Harden persistence for interrupted writes and concurrent uploads. Current import validation protects against invalid files, but writing JSON and CSV is not transactional.

## Local commands

- Run application: `python app.py`
- Install runtime: `python -m pip install -r requirements.txt`
- Install test dependencies: `python -m pip install -r requirements-dev.txt`
- Regression checks: `python -m unittest discover -s tests -v`
- JavaScript syntax: `node --check static/js/app.js`

This directory is a Git repository on `main`, with origin `https://github.com/yashmartand717/AI-INSIGHT.git`. Preserve `.env` and existing data. Credentials, local student data and Excel files are excluded from Git. Scratch scripts under `.system_generated` are support files, not part of the application.
