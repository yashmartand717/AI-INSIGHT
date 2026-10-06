"""
Cloud API AI Insight Generator for GyanBuddy School Management System.
Supports Google Gemini (Gemini 2.5/1.5 Flash via google-genai) and OpenAI (gpt-4o-mini).
Includes an intelligent mock engine as automatic fallback when no API key is provided,
allowing instant offline testing and live demonstration.
"""

import os
import json
import re
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from engine.product_rules import validate_recommendations
from engine.report_builder import build_from_metrics, REPORT_VERSION

from engine.analytics import analyze_student, analyze_class_subject, analyze_school_principal
from engine.prompt_templates import (
    PARENT_SYSTEM_PROMPT, PARENT_USER_PROMPT,
    TEACHER_SYSTEM_PROMPT, TEACHER_USER_PROMPT,
    PRINCIPAL_SYSTEM_PROMPT, PRINCIPAL_USER_PROMPT
)

load_dotenv()

# Pricing constants (USD per 1 Million tokens)
# Gemini 2.5/1.5 Flash: ~$0.075 / 1M prompt tokens, ~$0.30 / 1M output tokens
# GPT-4o-mini: ~$0.15 / 1M prompt tokens, ~$0.60 / 1M output tokens
GEMINI_INPUT_COST_PER_M = 0.075
GEMINI_OUTPUT_COST_PER_M = 0.30

def clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Clean markdown backticks and parse JSON safely."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    result = json.loads(text.strip())
    validate_recommendations(result)
    return result

class AIInsightGenerator:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.active_provider = self._detect_provider()

    def _detect_provider(self) -> str:
        preferred = os.environ.get("INSIGHTS_PROVIDER", "").strip().lower()
        if preferred == "rules":
            return "SMART_MOCK"
        if preferred in ("openai", "gemini"):
            return preferred.upper()
        if self.openai_key:
            return "OPENAI"
        if self.gemini_key:
            return "GEMINI"
        return "SMART_MOCK"

    def refresh_keys(self, gemini_key: Optional[str] = None, openai_key: Optional[str] = None):
        """Allows dynamically updating API keys from the UI/API without restart."""
        if gemini_key is not None:
            self.gemini_key = gemini_key
            os.environ["GEMINI_API_KEY"] = gemini_key
        if openai_key is not None:
            self.openai_key = openai_key
            os.environ["OPENAI_API_KEY"] = openai_key
        self.active_provider = self._detect_provider()

    def get_provider_status(self) -> Dict[str, Any]:
        load_dotenv(override=True)
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.active_provider = self._detect_provider()
        return {
            "active_provider": self.active_provider,
            "has_gemini_key": bool(self.gemini_key),
            "has_openai_key": bool(self.openai_key),
            "model_name": "Google Gemini Flash (Active)" if self.active_provider == "GEMINI" else (
                f"OpenAI {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}" if self.active_provider == "OPENAI" else "Smart Engine (Add GEMINI_API_KEY in .env)"
            )
        }

    def test_gemini_connection(self, key_to_test: str) -> Dict[str, Any]:
        """Validates a Gemini API key with a fast 1-token test ping."""
        from google import genai
        models_to_try = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.7-flash"]
        last_error = None
        for model in models_to_try:
            try:
                client = genai.Client(api_key=key_to_test.strip())
                res = client.models.generate_content(
                    model=model,
                    contents="Say OK",
                )
                if res and res.text:
                    return {"valid": True, "model": model, "message": f"Successfully connected to Google {model}!"}
            except Exception as e:
                last_error = str(e)
        return {"valid": False, "error": last_error or "Unknown connection failure"}

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        from google import genai
        client = genai.Client(api_key=self.gemini_key)
        models_to_try = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.7-flash"]
        last_exception = None

        for model in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config={
                        "system_instruction": system_prompt,
                        "response_mime_type": "application/json",
                        "temperature": 0.4
                    }
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_exception = e
                continue
        raise last_exception or Exception("Failed to get response from Gemini")

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.openai_key, timeout=60.0, max_retries=0)
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.4
        )
        return response.choices[0].message.content

    # ==================== PARENT REPORT ====================

    def generate_parent_report(self, student_id: str) -> Dict[str, Any]:
        metrics = analyze_student(student_id)
        if "error" in metrics:
            return metrics

        # Generate using Cloud API if available
        if self.active_provider == "GEMINI":
            try:
                user_msg = PARENT_USER_PROMPT.format(student_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_gemini(PARENT_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": "Gemini 2.5 Flash Cloud API",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] Gemini API call failed: {e}. Using Smart Engine.")

        elif self.active_provider == "OPENAI":
            try:
                user_msg = PARENT_USER_PROMPT.format(student_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_openai(PARENT_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": f"OpenAI {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] OpenAI API call failed: {e}. Using Smart Engine.")

        # Smart Fallback (Deterministic + Human-crafted Pedagogical Engine)
        return self._generate_mock_parent_report(metrics)

    def _generate_mock_parent_report(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        report = build_from_metrics(metrics)["insights"]["parent"]
        return {
            "source": "Rule-based analysis (Offline)",
            "report_version": REPORT_VERSION,
            "metrics": metrics,
            "ai_insight": {
                "headline": report["headline"],
                "overall_summary": report["summary"],
                "strength_highlight": report["strengths"],
                "focus_area_explanation": report["focus"],
                "action_plan_for_home": report["actions"],
                "follow_up": report["follow_up"],
                "evidence_note": report["evidence_note"],
                "whatsapp_message": (
                    f"Dear Parent, {report['summary']}\n\n"
                    f"What to build on: {report['strengths']}\n"
                    f"Next step: {report['actions'][0]}\n{report['follow_up']}\n"
                    f"{report['evidence_note']}\nAcademic Team, GyanBuddy"
                ),
            },
        }

    # ==================== TEACHER REPORT ====================

    def generate_teacher_report(self, class_name: str = "Class 9", section: str = "A", subject: str = "Science") -> Dict[str, Any]:
        metrics = analyze_class_subject(class_name, section, subject)
        if "error" in metrics:
            return metrics

        if self.active_provider == "GEMINI":
            try:
                user_msg = TEACHER_USER_PROMPT.format(class_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_gemini(TEACHER_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": "Gemini 2.5 Flash Cloud API",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] Gemini API call failed: {e}")

        elif self.active_provider == "OPENAI":
            try:
                user_msg = TEACHER_USER_PROMPT.format(class_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_openai(TEACHER_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": f"OpenAI {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] OpenAI API call failed: {e}")

        # Smart Fallback
        return self._generate_mock_teacher_report(metrics)

    def _generate_mock_teacher_report(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        clusters = metrics.get("remedial_clusters", [])
        cluster = clusters[0] if clusters else None
        chapter = cluster["chapter"] if cluster else "the recorded topics"
        return {
            "source": "Rule-based analysis (Offline)",
            "metrics": metrics,
            "ai_insight": {
                "subject_class_overview": (
                    f"{metrics['class_name']}-{metrics['section']} has a weighted score of "
                    f"{metrics['class_average_pct']}% in {metrics['subject']} across "
                    f"{metrics['total_test_attempts']} submitted "
                    f"{'result' if metrics['total_test_attempts'] == 1 else 'results'}. "
                    "This covers the uploaded work only; it does not establish a trend or syllabus readiness."
                ),
                "critical_learning_gap": (
                    f"{cluster['student_count']} {'student has' if cluster['student_count'] == 1 else 'students have'} an aggregate score below 50% in {chapter}. "
                    "Review marked answers and ask two diagnostic questions before identifying the cause."
                    if cluster else "No student-topic aggregate is below 50%. Review individual errors and any topics below 70% before deciding on support or extension."
                ),
                "remedial_group_strategy": {
                    "group_name": cluster["cluster_name"] if cluster else "Regular revision",
                    "students_involved": list(dict.fromkeys(s["student_name"] for s in cluster["students"])) if cluster else [],
                    "targeted_intervention": f"Use 15 minutes to review marked work in {chapter}, model one relevant example, then check three independent responses.",
                    "recommended_homework": f"Select three textbook questions covering {chapter}; ask students to show their reasoning and note any step where help is needed.",
                },
                "peer_learning_pairing": "Choose peer partners after reviewing individual answers and checking understanding.",
                "action_item_for_next_class": f"Review errors in {chapter}; after two practice opportunities, check new independent responses and adjust the support group.",
            },
        }

    # ==================== PRINCIPAL REPORT ====================

    def generate_principal_report(self) -> Dict[str, Any]:
        metrics = analyze_school_principal()
        if "error" in metrics:
            return metrics

        if self.active_provider == "GEMINI":
            try:
                user_msg = PRINCIPAL_USER_PROMPT.format(principal_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_gemini(PRINCIPAL_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": "Gemini 2.5 Flash Cloud API",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] Gemini API call failed: {e}")

        elif self.active_provider == "OPENAI":
            try:
                user_msg = PRINCIPAL_USER_PROMPT.format(principal_metrics_json=json.dumps(metrics, indent=2))
                raw_json = self._call_openai(PRINCIPAL_SYSTEM_PROMPT, user_msg)
                ai_data = clean_json_response(raw_json)
                return {
                    "source": f"OpenAI {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}",
                    "metrics": metrics,
                    "report_version": REPORT_VERSION,
                    "ai_insight": ai_data
                }
            except Exception as e:
                print(f"[AI Fallback] OpenAI API call failed: {e}")

        # Smart Fallback
        return self._generate_mock_principal_report(metrics)

    def _generate_mock_principal_report(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        bottlenecks = metrics.get("curriculum_bottlenecks", [])
        return {
            "source": "Rule-based analysis (Offline)",
            "metrics": metrics,
            "ai_insight": {
                "executive_summary": (
                    f"The uploaded work covers {metrics['total_active_students']} "
                    f"{'student' if metrics['total_active_students'] == 1 else 'students'} "
                    f"and has a weighted score of {metrics['school_overall_average_pct']}%. "
                    "This describes the supplied results, not a validated measure of school health. "
                    "Coverage, assessment difficulty and comparable historical results need review before drawing wider conclusions."
                ),
                "academic_health_score": round(metrics['school_overall_average_pct']),
                "top_bottlenecks": [
                    {
                        "subject": item["subject"],
                        "chapter": item["chapter"],
                        "concern": f"The recorded average is {item['average_pct']}%.",
                        "suggested_administrative_action": "Ask the subject teacher to review marked work and assessment difficulty, agree on a support goal, and check independent responses after two practice opportunities.",
                    } for item in bottlenecks
                ],
                "teacher_support_recommendations": (
                    "Agree with the relevant teachers who will provide support and a follow-up date. Review fresh assessment evidence before extending the intervention."
                    if bottlenecks else "No chapter average falls below 50%. Continue monitoring future assessments."
                ),
                "parent_community_alignment": "Share individual progress and practical revision suggestions with parents.",
            },
        }

    # ==================== COST ESTIMATOR ====================

    @staticmethod
    def calculate_cost_estimate(student_count: int = 1500, frequency: str = "monthly") -> Dict[str, Any]:
        """
        Calculates exact token and financial expenditure for a school using Cloud APIs.
        Frequency: 'weekly' (4 reports/month) or 'monthly' (1 report/month).
        """
        reports_per_student = 4 if frequency.lower() == "weekly" else 1
        total_reports = student_count * reports_per_student

        # Per student call: ~300 input tokens, ~150 output tokens
        total_input_tokens = total_reports * 300
        total_output_tokens = total_reports * 150

        # Plus teacher calls: 1 call per class-subject (approx 30 classes * 4 subjects = 120 calls/month)
        teacher_calls = 120
        total_input_tokens += teacher_calls * 600
        total_output_tokens += teacher_calls * 350

        # Plus principal calls: 4 calls/month
        principal_calls = 4
        total_input_tokens += principal_calls * 800
        total_output_tokens += principal_calls * 400

        # Gemini Flash cost
        gemini_input_cost = (total_input_tokens / 1_000_000) * GEMINI_INPUT_COST_PER_M
        gemini_output_cost = (total_output_tokens / 1_000_000) * GEMINI_OUTPUT_COST_PER_M
        gemini_total_usd = gemini_input_cost + gemini_output_cost
        gemini_total_inr = gemini_total_usd * 86.5  # approx conversion

        return {
            "student_count": student_count,
            "frequency": frequency,
            "total_reports_generated": total_reports,
            "total_tokens_estimated": total_input_tokens + total_output_tokens,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "gemini_total_usd": round(gemini_total_usd, 3),
            "gemini_total_inr": round(gemini_total_inr, 2),
            "cost_per_student_per_month_usd": round(gemini_total_usd / student_count, 5),
            "cost_per_student_per_month_inr": round(gemini_total_inr / student_count, 3)
        }
