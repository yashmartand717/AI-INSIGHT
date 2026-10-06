"""Known GyanBuddy capabilities, shared across report generation paths."""
import re

CAPABILITY_RULES = """
GyanBuddy does not provide recorded lectures, lecture recordings or video lessons.
Never recommend watching, replaying or accessing recorded lectures/classes/lessons,
and never imply such content is available in the app.
Recommend textbook revision, written practice, reviewing test mistakes, teacher-led
explanation and parent-supported study instead. Do not invent app resources,
unlocked practice sets, scheduled sessions or other unverified features.
"""


REPORT_QUALITY_RULES = """
Write audience-specific, evidence-based reports with correct singular/plural grammar.
Count submitted results, not distinct tests: multiple rows may belong to one assessment.
Use exact scores and topic names. Combine repeated topic rows using earned/available totals.
Never describe the same aggregate topic as both a strength and a gap.
Do not infer effort, habits, engagement, specific misconceptions, syllabus pacing or causes from scores.
A single result is a snapshot, not evidence of improvement, decline or overall ability.
For low scores, identify a constructive starting point without inventing strengths or praising unseen effort.
Give three practical suggested actions and a follow-up check of independent work, appropriate to the audience.
For strong results, suggest consolidation and extension, not automatic remediation.
Explain the limits of the supplied evidence. No question-level answers means no known conceptual diagnosis.
For an individual principal report, do not infer school-wide problems from one student.
Include follow_up and evidence_note fields when supported by the output schema.
"""


class UnsupportedRecommendation(ValueError):
    pass


def validate_recommendations(content):
    """Reject unsupported lesson-media claims before displaying or emailing them."""
    if isinstance(content, dict):
        for value in content.values():
            validate_recommendations(value)
    elif isinstance(content, list):
        for value in content:
            validate_recommendations(value)
    elif isinstance(content, str):
        patterns = (
            r"\b(?:recorded|pre[ -]?recorded|video)\s+(?:\w+\s+){0,3}(?:lectures?|lessons?|classes|sessions?|tutorials?)\b",
            r"\b(?:lecture|lesson|class)\s+(?:recordings?|videos?)\b",
        )
        if any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns):
            raise UnsupportedRecommendation("GyanBuddy does not offer recorded lectures or video lessons")
