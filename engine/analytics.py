"""
Deterministic Analytics Engine for GyanBuddy School Management System.
Computes mathematical metrics, mastery thresholds, student clusters, and performance deltas
purely in Python to guarantee 100% factual accuracy and zero token hallucination.
"""

from typing import Dict, List, Any
import json
import os
import hashlib
import math
import pandas as pd

MASTERY_THRESHOLDS = {
    "CRITICAL_GAP": 40.0,    # Score < 40%
    "NEEDS_REVISION": 70.0,  # 40% <= Score < 70%
    "MASTERED": 100.0        # Score >= 70%
}

def load_test_data(data_path: str = "data/students_test_data.json") -> List[Dict[str, Any]]:
    if not os.path.exists(data_path):
        if os.path.exists("data/students_test_data.csv"):
            df = pd.read_csv("data/students_test_data.csv")
            return df.to_dict(orient="records")
        return []
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)

def import_and_normalize_csv(file_content_or_path, is_bytes: bool = False) -> Dict[str, Any]:
    """
    Imports and normalizes any school test CSV or Excel file with smart column mapping.
    Handles headers like: Student Name, Marks, Chapter, Score, Out of, etc.
    """
    import io
    if is_bytes:
        try:
            df = pd.read_csv(io.BytesIO(file_content_or_path), dtype=str, keep_default_na=False)
        except Exception:
            try:
                df = pd.read_excel(io.BytesIO(file_content_or_path), dtype=str, keep_default_na=False)
            except Exception as e:
                return {"error": f"Failed to parse file: {str(e)}"}
    else:
        try:
            if str(file_content_or_path).lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(file_content_or_path, dtype=str, keep_default_na=False)
            else:
                df = pd.read_csv(file_content_or_path, dtype=str, keep_default_na=False)
        except Exception as e:
            return {"error": f"Failed to parse file: {e}"}

    if df.empty:
        return {"error": "Uploaded file is empty"}

    # Helper column matcher
    col_map = {}
    clean_cols = {c: str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns}

    aliases = {
        "student_name": ["student_name", "studentname", "name", "student", "candidate_name"],
        "student_id": ["student_id", "studentid", "id", "reg_no", "admission_no"],
        "roll_no": ["roll_no", "rollno", "roll_number"],
        "class_name": ["class_name", "class", "grade", "standard", "std"],
        "section": ["section", "sec"],
        "subject": ["subject", "subj", "course"],
        "chapter": ["chapter", "topic", "unit", "lesson"],
        "subtopic": ["subtopic", "concept", "sub_topic", "details", "topic_detail"],
        "total_questions": ["total_questions", "total", "max_marks", "total_marks", "questions", "out_of", "max"],
        "attempted": ["attempted", "attended", "attempt", "total_attempted"],
        "correct": ["correct", "marks", "score", "marks_obtained", "correct_answers", "result"],
        "test_date": ["test_date", "date", "exam_date"]
    }

    for target_key, alias_list in aliases.items():
        for orig_col, clean_col in clean_cols.items():
            if clean_col in alias_list and target_key not in col_map:
                col_map[target_key] = orig_col
                break

    missing = [key for key in ("student_name", "correct", "total_questions") if key not in col_map]
    if missing:
        return {"error": "Missing required columns: " + ", ".join(missing)}

    # Reject the entire import before saving if any populated row is invalid.
    records = []
    identities = {}
    warnings = set()

    def cell(row, key, default=""):
        value = row[col_map[key]] if key in col_map else ""
        return str(value).strip() if pd.notna(value) and str(value).strip() else default

    for row_index, row in df.iterrows():
        if all(not str(value).strip() or pd.isna(value) for value in row):
            continue
        # Name
        name = cell(row, "student_name")
        if not name:
            return {"error": f"Row {row_index + 2}: student_name is required."}

        # ID
        sid = cell(row, "student_id")

        # Class & Section
        cname = cell(row, "class_name", "Unspecified class")
        if cname != "Unspecified class" and not cname.lower().startswith("class"):
            cname = f"Class {cname}"
        sec = cell(row, "section", "Unspecified section")
        roll_no = cell(row, "roll_no")
        if not sid:
            identity = [cname.casefold(), sec.casefold(), roll_no or name.casefold()]
            sid = "AUTO-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
            warnings.add("Missing student IDs were grouped by class, section and roll number or name. Supply unique student IDs to distinguish namesakes.")
        identity = (name.casefold(), cname.casefold(), sec.casefold())
        if sid in identities and identities[sid] != identity:
            return {"error": f"Row {row_index + 2}: student ID {sid} refers to conflicting students or classes."}
        identities[sid] = identity

        # Subject & Chapter
        subj = cell(row, "subject", "Unspecified subject")
        chap = cell(row, "chapter", "Unspecified chapter")
        subtopic = cell(row, "subtopic")
        if any(not cell(row, key) for key in ("class_name", "section", "subject", "chapter")):
            warnings.add("Missing class, section, subject or chapter values are shown as unspecified.")

        # Scores
        try:
            total_q = float(cell(row, "total_questions"))
            correct_q = float(cell(row, "correct"))
            attempted_q = float(cell(row, "attempted", str(total_q)))
            if not all(math.isfinite(n) for n in (total_q, correct_q, attempted_q)):
                raise ValueError("scores must be finite numbers")
            if not (total_q > 0 and 0 <= correct_q <= attempted_q <= total_q):
                raise ValueError("require total > 0 and 0 <= correct <= attempted <= total")
        except (ValueError, TypeError) as e:
            return {"error": f"Row {row_index + 2}: invalid scores ({e})."}

        t_date = cell(row, "test_date")

        records.append({
            "student_id": sid,
            "student_name": name,
            "roll_no": roll_no,
            "class_name": cname,
            "section": sec,
            "subject": subj,
            "chapter": chap,
            "subtopic": subtopic,
            "total_questions": total_q,
            "attempted": attempted_q,
            "correct": correct_q,
            "test_date": t_date,
        })

    if not records:
        return {"error": "No valid student test rows could be extracted from the file."}

    # Save to disk
    os.makedirs("data", exist_ok=True)
    with open("data/students_test_data.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    df_out = pd.DataFrame(records)
    df_out.to_csv("data/students_test_data.csv", index=False)

    # Invalidate cache so fresh reports generate
    cache_path = "data/generated_reports_cache.json"
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
        except Exception:
            pass

    unique_students = list(dict.fromkeys(r["student_name"] for r in records))
    unique_subjects = list(dict.fromkeys(r["subject"] for r in records))

    return {
        "status": "success",
        "total_records": len(records),
        "total_students": len(identities),
        "warnings": sorted(warnings),
        "students": unique_students,
        "subjects": unique_subjects,
        "first_student_id": records[0]["student_id"]
    }

def classify_mastery(score_pct: float) -> str:
    if score_pct < MASTERY_THRESHOLDS["CRITICAL_GAP"]:
        return "CRITICAL_GAP"
    elif score_pct < MASTERY_THRESHOLDS["NEEDS_REVISION"]:
        return "NEEDS_REVISION"
    else:
        return "MASTERED"

def analyze_student(student_id: str, test_records: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Computes deep performance metrics for a single student across all their tests.
    """
    if test_records is None:
        test_records = load_test_data()

    student_tests = [t for t in test_records if t["student_id"] == student_id]
    if not student_tests:
        return {"error": f"Student with ID {student_id} not found"}

    student_name = student_tests[0]["student_name"]
    class_name = student_tests[0]["class_name"]
    section = student_tests[0]["section"]

    total_attempted = sum(t["attempted"] for t in student_tests)
    total_correct = sum(t["correct"] for t in student_tests)
    total_questions = sum(t["total_questions"] for t in student_tests)
    overall_accuracy = round((total_correct / total_questions) * 100, 1) if total_questions > 0 else 0

    # Subject and Chapter breakdowns
    subjects_dict = {}
    chapter_diagnostics = []

    for t in student_tests:
        subj = t["subject"]
        chap = t["chapter"]
        subtopic = t.get("subtopic", "")
        q_count = t["total_questions"]
        c_count = t["correct"]
        pct = round((c_count / q_count) * 100, 1)
        prev_pct = t.get("previous_score_pct")
        delta = round(pct - prev_pct, 1) if prev_pct is not None else None
        mastery = classify_mastery(pct)

        if subj not in subjects_dict:
            subjects_dict[subj] = {
                "total_q": 0,
                "correct_q": 0,
                "tests_count": 0
            }
        subjects_dict[subj]["total_q"] += q_count
        subjects_dict[subj]["correct_q"] += c_count
        subjects_dict[subj]["tests_count"] += 1

        chapter_diagnostics.append({
            "subject": subj,
            "chapter": chap,
            "subtopic": subtopic,
            "attempted": t["attempted"],
            "correct": c_count,
            "total_questions": q_count,
            "score_pct": pct,
            "previous_score_pct": prev_pct,
            "delta": delta,
            "mastery_status": mastery,
            "test_date": t.get("test_date", "")
        })

    subject_summaries = {}
    for subj, data in subjects_dict.items():
        acc = round((data["correct_q"] / data["total_q"]) * 100, 1) if data["total_q"] > 0 else 0
        subject_summaries[subj] = {
            "accuracy_pct": acc,
            "mastery_status": classify_mastery(acc),
            "tests_evaluated": data["tests_count"]
        }

    # Sort chapters into critical gaps and strengths
    critical_gaps = [c for c in chapter_diagnostics if c["mastery_status"] == "CRITICAL_GAP"]
    needs_revision = [c for c in chapter_diagnostics if c["mastery_status"] == "NEEDS_REVISION"]
    strengths = [c for c in chapter_diagnostics if c["mastery_status"] == "MASTERED"]

    # Sort by urgency
    critical_gaps.sort(key=lambda x: x["score_pct"])
    strengths.sort(key=lambda x: x["score_pct"], reverse=True)

    return {
        "student_id": student_id,
        "student_name": student_name,
        "roll_no": student_tests[0].get("roll_no"),
        "class_name": class_name,
        "section": section,
        "overall_accuracy_pct": overall_accuracy,
        "total_tests_taken": len(student_tests),
        "subject_summaries": subject_summaries,
        "chapter_diagnostics": chapter_diagnostics,
        "critical_gaps": critical_gaps,
        "needs_revision": needs_revision,
        "strengths": strengths,
        "has_urgent_remedial": len(critical_gaps) > 0
    }

def analyze_class_subject(class_name: str = "Class 9", section: str = "A", subject: str = "Science", test_records: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Computes class-level diagnostics and clusters students with identical knowledge gaps.
    Saves massive API costs by summarizing an entire section in one call.
    """
    if test_records is None:
        test_records = load_test_data()

    filtered = [
        t for t in test_records
        if t["class_name"].lower() == class_name.lower()
        and t["section"].lower() == section.lower()
        and t["subject"].lower() == subject.lower()
    ]

    if not filtered:
        return {"error": f"No records found for {class_name}-{section} {subject}"}

    # Calculate chapter performance
    chapters_data = {}
    for t in filtered:
        chap = t["chapter"]
        if chap not in chapters_data:
            chapters_data[chap] = {
                "chapter": chap,
                "total_questions": 0,
                "correct_answers": 0,
                "student_scores": [],
                "struggling_students": [],
                "mastered_students": []
            }

        pct = round((t["correct"] / t["total_questions"]) * 100, 1)
        chapters_data[chap]["total_questions"] += t["total_questions"]
        chapters_data[chap]["correct_answers"] += t["correct"]

        student_info = {
            "student_id": t["student_id"],
            "student_name": t["student_name"],
            "score_pct": pct,
            "correct": t["correct"],
            "total": t["total_questions"],
            "subtopic": t.get("subtopic", "")
        }
        chapters_data[chap]["student_scores"].append(student_info)

        if pct < 50.0:
            chapters_data[chap]["struggling_students"].append(student_info)
        elif pct >= 70.0:
            chapters_data[chap]["mastered_students"].append(student_info)

    # Compute averages and build remedial clusters
    chapter_stats = []
    remedial_clusters = []

    for chap, data in chapters_data.items():
        avg_score = round((data["correct_answers"] / data["total_questions"]) * 100, 1)
        chapter_stats.append({
            "chapter": chap,
            "class_average_pct": avg_score,
            "total_students_tested": len(data["student_scores"]),
            "struggling_count": len(data["struggling_students"]),
            "mastered_count": len(data["mastered_students"]),
            "mastery_status": classify_mastery(avg_score)
        })

        if len(data["struggling_students"]) > 0:
            remedial_clusters.append({
                "cluster_name": f"{chap} Remedial Intervention Group",
                "chapter": chap,
                "students": data["struggling_students"],
                "student_count": len(data["struggling_students"]),
                "recommended_focus": "Numerical formulas, core derivations, and step-by-step problem breakdown"
            })

    total_q = sum(t["total_questions"] for t in filtered)
    total_c = sum(t["correct"] for t in filtered)
    class_subject_avg = round((total_c / total_q) * 100, 1) if total_q > 0 else 0

    return {
        "class_name": class_name,
        "section": section,
        "subject": subject,
        "class_average_pct": class_subject_avg,
        "total_test_attempts": len(filtered),
        "chapter_stats": chapter_stats,
        "remedial_clusters": remedial_clusters,
        "most_critical_chapter": min(chapter_stats, key=lambda x: x["class_average_pct"]) if chapter_stats else None
    }

def analyze_school_principal(test_records: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Computes macro, high-level indicators across the entire school/grades for the Principal.
    """
    if test_records is None:
        test_records = load_test_data()

    if not test_records:
        return {"error": "No records found"}

    unique_students = len(set(t["student_id"] for t in test_records))
    total_tests = len(test_records)
    total_q = sum(t["total_questions"] for t in test_records)
    total_c = sum(t["correct"] for t in test_records)
    school_avg = round((total_c / total_q) * 100, 1) if total_q > 0 else 0

    # Group by Subject
    subjects_summary = {}
    for t in test_records:
        subj = t["subject"]
        if subj not in subjects_summary:
            subjects_summary[subj] = {"total_q": 0, "correct_q": 0, "attempts": 0, "critical_count": 0}
        subjects_summary[subj]["total_q"] += t["total_questions"]
        subjects_summary[subj]["correct_q"] += t["correct"]
        subjects_summary[subj]["attempts"] += 1
        pct = (t["correct"] / t["total_questions"]) * 100
        if pct < 40.0:
            subjects_summary[subj]["critical_count"] += 1

    subject_breakdown = []
    for subj, d in subjects_summary.items():
        avg = round((d["correct_q"] / d["total_q"]) * 100, 1)
        critical_pct = round((d["critical_count"] / d["attempts"]) * 100, 1)
        subject_breakdown.append({
            "subject": subj,
            "average_pct": avg,
            "attempts": d["attempts"],
            "critical_gap_students_pct": critical_pct,
            "status": "RED" if critical_pct > 35 else ("YELLOW" if critical_pct > 15 else "GREEN")
        })

    # Find highest risk chapters
    chap_dict = {}
    for t in test_records:
        key = (t["subject"], t["chapter"])
        if key not in chap_dict:
            chap_dict[key] = {"total_q": 0, "correct_q": 0, "attempts": 0}
        chap_dict[key]["total_q"] += t["total_questions"]
        chap_dict[key]["correct_q"] += t["correct"]
        chap_dict[key]["attempts"] += 1

    bottlenecks = []
    for (subj, chap), d in chap_dict.items():
        avg = round((d["correct_q"] / d["total_q"]) * 100, 1)
        if avg < 50.0:
            bottlenecks.append({
                "subject": subj,
                "chapter": chap,
                "average_pct": avg,
                "attempts": d["attempts"]
            })

    bottlenecks.sort(key=lambda x: x["average_pct"])

    return {
        "total_active_students": unique_students,
        "total_tests_processed": total_tests,
        "school_overall_average_pct": school_avg,
        "subject_breakdown": subject_breakdown,
        "curriculum_bottlenecks": bottlenecks,
        "action_required": len(bottlenecks) > 0
    }

if __name__ == "__main__":
    # Test with Abhishek
    abhishek = analyze_student("STU101")
    print(f"Abhishek Analysis: Overall {abhishek['overall_accuracy_pct']}%, Critical Gaps: {len(abhishek['critical_gaps'])}")
    for gap in abhishek['critical_gaps']:
        print(f"  -> {gap['subject']} - {gap['chapter']}: {gap['score_pct']}% ({gap['correct']}/{gap['total_questions']})")

    # Test Class 9-A Science
    science_class = analyze_class_subject("Class 9", "A", "Science")
    print(f"\nClass 9-A Science: Avg {science_class['class_average_pct']}%, Remedial Clusters: {len(science_class['remedial_clusters'])}")
    for cluster in science_class['remedial_clusters']:
        students = ", ".join([s["student_name"] for s in cluster["students"]])
        print(f"  -> {cluster['cluster_name']}: [{students}]")
