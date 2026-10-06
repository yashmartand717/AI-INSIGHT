"""Persistent local progress preview with a pluggable report builder; no mail transport."""
import json
import sqlite3
import uuid
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from .report_builder import build_rules_report, REPORT_VERSION


class ProgressPreview:
    def __init__(self, path=".system_generated/progress.sqlite3", recover_interrupted=True, builder=None):
        self.builder = builder
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-insights")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, created TEXT, records TEXT, reports TEXT)")
        if recover_interrupted:
            self.recover_interrupted()

    def recover_interrupted(self):
        # Called at server startup, not when imported by a separate test process.
        with self.connect() as db:
            for bid, reports in db.execute("SELECT id, reports FROM batches").fetchall():
                rows = json.loads(reports)
                for row in rows:
                    if row["state"] in ("queued", "processing"):
                        row.update(state="failed", error_code="PreviewRestarted")
                db.execute("UPDATE batches SET reports=? WHERE id=?", (json.dumps(rows), bid))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def refresh_ready_reports(self):
        """Upgrade local offline previews from their original snapshots, with a backup."""
        with self.lock, self.connect() as db:
            updates = []
            count = 0
            for bid, records, reports in db.execute("SELECT id, records, reports FROM batches").fetchall():
                grouped, rows = json.loads(records), json.loads(reports)
                changed = False
                for row in rows:
                    report = row.get("report", {})
                    if row["state"] == "ready" and report.get("source") == "rules" and report.get("report_version") != REPORT_VERSION:
                        row["report"] = build_rules_report(grouped[row["student_id"]])
                        changed = True
                        count += 1
                if changed:
                    updates.append((json.dumps(rows), bid))
            if updates:
                backup_path = self.path.with_name(f"{self.path.stem}.before-{REPORT_VERSION}-{uuid.uuid4().hex[:8]}.sqlite3")
                with closing(sqlite3.connect(backup_path)) as backup:
                    db.backup(backup)
                db.executemany("UPDATE batches SET reports=? WHERE id=?", updates)
            return count

    def start(self, records, background=True):
        if not records:
            raise ValueError("Upload marks in the report dashboard first.")
        grouped = defaultdict(list)
        for row in records:
            grouped[str(row["student_id"])].append(row)
        reports = [{"student_id": sid, "student_name": rows[0]["student_name"], "state": "queued", "error_code": "", "report": {}} for sid, rows in grouped.items()]
        bid = str(uuid.uuid4())
        with self.lock, self.connect() as db:
            # An accidental repeated click returns the active local batch.
            for existing, stored in db.execute("SELECT id, reports FROM batches ORDER BY created DESC LIMIT 1"):
                if any(r["state"] in ("queued", "processing") for r in json.loads(stored)):
                    return existing
            db.execute("INSERT INTO batches VALUES (?,?,?,?)", (bid, datetime.now(timezone.utc).isoformat(), json.dumps(grouped), json.dumps(reports)))
        if background:
            self.executor.submit(self.run, bid)
        return bid

    def run(self, bid):
        with self.connect() as db:
            record = db.execute("SELECT records, reports FROM batches WHERE id=?", (bid,)).fetchone()
        if not record:
            return
        grouped, reports = map(json.loads, record)
        for row in reports:
            row["state"] = "processing"
            self.save(bid, reports)
            try:
                row.update(report=(self.builder or build_rules_report)(grouped[row["student_id"]]), state="ready", error_code="")
            except Exception as exc:
                row.update(state="failed", error_code=type(exc).__name__)
            self.save(bid, reports)

    def save(self, bid, reports):
        with self.connect() as db:
            db.execute("UPDATE batches SET reports=? WHERE id=?", (json.dumps(reports), bid))

    def get(self, bid):
        with self.connect() as db:
            row = db.execute("SELECT created,reports FROM batches WHERE id=?", (bid,)).fetchone()
        if not row:
            raise KeyError(bid)
        created, serialized = row
        reports = json.loads(serialized)
        counts = Counter(r["state"] for r in reports)
        status = "processing" if counts["processing"] or counts["queued"] else "failed" if counts["failed"] else "ready"
        return {"id": bid, "event_id": "Local marks analysis", "created_at": created,
                "status": status, "total_students": len(reports), "ready_students": counts["ready"],
                "report_states": dict(counts), "email_states": {}, "published_at": None, "results": reports}

    def list(self, offset=0):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM batches ORDER BY created DESC LIMIT 20 OFFSET ?", (offset,))]
            count = db.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        return {"count": count, "results": [{k: v for k, v in self.get(bid).items() if k != "results"} for bid in ids]}
