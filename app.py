"""
FastAPI Backend and Interactive Web Dashboard for GyanBuddy AI Insight Tool.
Exposes REST endpoints for Parents, Teachers, Principals, Batch processing, and Cost Simulation.
"""

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from contextlib import asynccontextmanager

from engine.analytics import load_test_data, analyze_student, analyze_class_subject, analyze_school_principal, import_and_normalize_csv
from engine.ai_generator import AIInsightGenerator
from engine.batch_worker import BatchWorker
from engine.progress_preview import ProgressPreview
from gyanbuddy_insights.generation import generate_local, local_configuration

@asynccontextmanager
async def app_lifespan(application):
    progress_preview.recover_interrupted()
    progress_preview.refresh_ready_reports()
    yield
    progress_preview.executor.shutdown(wait=True)

app = FastAPI(
    title="GyanBuddy AI Insight Engine",
    description="Automated, cost-efficient academic intelligence for Parents, Teachers, and Principals",
    version="1.0.0",
    lifespan=app_lifespan,
)

# Mount static directory for the web UI
app.mount("/static", StaticFiles(directory="static"), name="static")

generator = AIInsightGenerator()
batch_worker = BatchWorker(concurrency_limit=5)
progress_preview = ProgressPreview(recover_interrupted=False, builder=generate_local)

class KeyUpdateRequest(BaseModel):
    gemini_key: Optional[str] = None
    openai_key: Optional[str] = None

class BatchRunRequest(BaseModel):
    concurrency: int = 5
    stagger_delay_ms: int = 50

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

@app.get("/api/status")
def get_system_status():
    records = load_test_data()
    unique_students = len(set(r["student_id"] for r in records)) if records else 0
    provider_info = generator.get_provider_status()
    return {
        "status": "online",
        "provider": provider_info,
        "total_test_records": len(records),
        "total_active_students": unique_students,
        "supported_roles": ["Parent", "Teacher", "Principal"]
    }

@app.get("/api/students")
def get_students_list():
    records = load_test_data()
    students_map = {}
    for r in records:
        sid = r["student_id"]
        if sid not in students_map:
            students_map[sid] = {
                "student_id": sid,
                "student_name": r["student_name"],
                "roll_no": r.get("roll_no", 0),
                "class_name": r["class_name"],
                "section": r["section"],
                "tests_count": 0,
                "total_q": 0,
                "correct_q": 0,
                "critical_gaps_count": 0
            }
        students_map[sid]["tests_count"] += 1
        students_map[sid]["total_q"] += r["total_questions"]
        students_map[sid]["correct_q"] += r["correct"]
        if (r["correct"] / r["total_questions"]) < 0.4:
            students_map[sid]["critical_gaps_count"] += 1

    students_list = []
    for sid, s in students_map.items():
        avg = round((s["correct_q"] / s["total_q"]) * 100, 1) if s["total_q"] > 0 else 0
        s["overall_accuracy_pct"] = avg
        students_list.append(s)

    students_list.sort(key=lambda x: (x["class_name"], x["section"], str(x["roll_no"]).zfill(12), x["student_name"]))
    return {"students": students_list}

@app.get("/api/report-groups")
def get_report_groups():
    groups = sorted({(r["class_name"], r["section"], r["subject"]) for r in load_test_data()})
    return {"groups": [dict(zip(("class_name", "section", "subject"), group)) for group in groups]}

@app.get("/api/reports/parent/{student_id}")
def get_parent_report(student_id: str):
    report = generator.generate_parent_report(student_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report

@app.get("/api/reports/teacher/{class_name}/{section}/{subject}")
def get_teacher_report(class_name: str, section: str, subject: str):
    report = generator.generate_teacher_report(class_name, section, subject)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report

@app.get("/api/reports/principal")
def get_principal_report():
    report = generator.generate_principal_report()
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report

@app.get("/api/cost-calculator")
def get_cost_calculator(
    students: int = Query(1500, description="Total number of students"),
    frequency: str = Query("monthly", description="'weekly' or 'monthly'")
):
    return generator.calculate_cost_estimate(students, frequency)

@app.post("/api/upload-csv")
async def upload_csv_file(file: UploadFile = File(...)):
    """Uploads and normalizes any school test CSV or Excel file."""
    try:
        if batch_worker.is_running:
            raise HTTPException(status_code=409, detail="Wait for the current batch to finish before replacing test data.")
        if not (file.filename or "").lower().endswith((".csv", ".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="Choose a CSV or Excel file.")
        content = await file.read()
        res = import_and_normalize_csv(content, is_bytes=True)
        if "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")

@app.get("/api/download-template")
def download_sample_template():
    """Provides a sample CSV template for schools."""
    template_path = "data/gyanbuddy_sample_template.csv"
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(
        template_path,
        media_type="text/csv",
        filename="gyanbuddy_test_template.csv"
    )

@app.post("/api/batch/run")
async def trigger_batch_run(payload: BatchRunRequest, background_tasks: BackgroundTasks):
    if batch_worker.is_running:
        return {"status": "already_running", "progress": batch_worker.progress}

    batch_worker.concurrency_limit = payload.concurrency
    batch_worker.delay_between_batches_sec = payload.stagger_delay_ms / 1000.0

    background_tasks.add_task(batch_worker.run_batch)
    return {"status": "started", "message": "Batch report generation launched in background"}

@app.get("/api/batch/progress")
def get_batch_progress():
    return batch_worker.progress

@app.get("/api/data/raw")
def get_raw_data():
    records = load_test_data()
    return {"records": records}

@app.get("/api/integration/guide")
def integration_guide():
    return FileResponse("docs/DJANGO_INTEGRATION.md", media_type="text/plain; charset=utf-8")

@app.get("/progress")
def progress_page():
    return FileResponse("gyanbuddy_insights/templates/gyanbuddy_insights/dashboard.html")

@app.get("/api/progress/config/")
def progress_config():
    config = local_configuration()
    provider = config["provider"]
    label = {"openai": "OpenAI", "gemini": "Gemini", "rules": "Rule-based"}.get(provider, "Invalid provider")
    return {"mode": "local", "can_generate": True, "can_send": False,
            "provider": provider, "model": config["model"],
            "description": f"Local preview · {label} reports from your uploaded marks. Email is not connected."}

@app.get("/api/progress/batches/")
def progress_batches(offset: int = Query(0, ge=0)):
    return progress_preview.list(offset)

@app.post("/api/progress/batches/", status_code=202)
def start_progress_batch():
    try:
        bid = progress_preview.start(load_test_data())
        return {k: v for k, v in progress_preview.get(bid).items() if k != "results"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/progress/batches/{batch_id}/")
def progress_batch(batch_id: str):
    try:
        return {k: v for k, v in progress_preview.get(batch_id).items() if k != "results"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Batch not found")

@app.get("/api/progress/batches/{batch_id}/reports/")
def progress_reports(batch_id: str, offset: int = Query(0, ge=0)):
    try:
        batch = progress_preview.get(batch_id)
        return {"count": batch["total_students"], "results": batch["results"][offset:offset + 50]}
    except KeyError:
        raise HTTPException(status_code=404, detail="Batch not found")

@app.get("/api/progress/batches/{batch_id}/emails/")
def progress_emails(batch_id: str):
    try:
        progress_preview.get(batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"count": 0, "results": [], "message": "Email delivery requires the Django backend connection."}

@app.get("/api/integration/package")
def integration_package():
    path = "dist/gyanbuddy-email-integration.zip"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Build the developer package first")
    return FileResponse(path, media_type="application/zip", filename="gyanbuddy-email-integration.zip")

if __name__ == "__main__":
    import uvicorn
    print("\nStarting GyanBuddy AI Insight Engine on http://localhost:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
