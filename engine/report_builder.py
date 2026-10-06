"""Offline role-specific reports shared by the preview and Django worker."""
from .analytics import analyze_student

REPORT_VERSION = "2026-10-06.2"


def topic_results(metrics):
    """Combine repeated results without treating rows as different topics or tests."""
    topics = {}
    for row in metrics["chapter_diagnostics"]:
        key = (row["subject"], row["chapter"])
        item = topics.setdefault(key, {"subject": key[0], "chapter": key[1], "correct": 0, "total": 0, "count": 0})
        item["correct"] += row["correct"]
        item["total"] += row["total_questions"]
        item["count"] += 1
    for item in topics.values():
        item["score_pct"] = round(100 * item["correct"] / item["total"], 1)
    return sorted(topics.values(), key=lambda item: (item["score_pct"], item["subject"], item["chapter"]))


def build_from_metrics(metrics):
    topics = topic_results(metrics)
    priority, best = topics[0], topics[-1]
    topic = f"{priority['chapter']} ({priority['subject']})"
    name = metrics["student_name"]
    count = len(metrics["chapter_diagnostics"])
    earned = sum(t["correct"] for t in topics)
    total = sum(t["total"] for t in topics)
    score = f"{earned:g} out of {total:g} ({metrics['overall_accuracy_pct']:g}%)"
    summary = (f"{name} scored {score} in {topic}." if count == 1 else
               f"Across {count} submitted results, {name} earned {score} in total.")
    needs_support = priority["score_pct"] < 70
    if best["score_pct"] >= 70:
        strengths = (f"{best['chapter']} ({best['subject']}) has a recorded score of {best['score_pct']:g}%. "
                     "Build on this by explaining an answer that earned credit and trying a new example.")
    elif earned > 0:
        strengths = ("Some credit was earned in the submitted work. Start with an answer that earned credit "
                     "and ask the student to explain it; this can help identify what to build on.")
    else:
        strengths = ("This result does not yet show which parts the student can do independently. "
                     "A short guided task can help find a starting point for support.")
    if needs_support:
        focus = (f"Start with {topic}: {priority['correct']:g} out of {priority['total']:g} "
                 f"({priority['score_pct']:g}%). Review the marked answers to find which steps need practice; "
                 "the score alone cannot explain the difficulty.")
    else:
        focus = ("Every recorded topic has an aggregate score of at least 70%. Consolidate this learning "
                 "with new questions and explanations before moving to more challenging work.")
    evidence = ("Based on one submitted result; this is a snapshot, not a full assessment of ability. " if count == 1 else
                f"Based on {count} submitted results, which may include parts of the same assessment. "
                "Overall and topic percentages use total credit earned divided by total available. ")
    evidence += "Question-level answers were not supplied, so specific misconceptions, effort and study habits cannot be inferred. "
    evidence += ("No historical comparison was supplied, so improvement or decline cannot be established." if
                 all(r.get("previous_score_pct") is None for r in metrics["chapter_diagnostics"]) else
                 "Historical scores are provided; check that the assessments are comparable before interpreting changes.")
    actions = {
        "parent": [
            f"Set aside 10–15 minutes for {topic}. Ask your child to explain one textbook example in their own words; note where help is needed.",
            "Invite your child to try three similar textbook questions independently, then review the answers together. You do not need to teach unfamiliar content.",
            "Share any unclear questions with the subject teacher. At the next practice session, ask your child to retry one question without help.",
        ],
        "teacher": [
            f"Review the marked work in {topic} and use two short diagnostic questions to identify the steps that need support.",
            "Model one worked example, then give three similar questions for independent practice. Record which responses need prompting.",
            "After two practice opportunities, use a few new questions on the same skill and compare independent responses before choosing the next teaching step.",
        ],
        "principal": [
            f"Ask the {priority['subject']} teacher to review this student's marked work in {priority['chapter']} and propose a specific support goal.",
            "Agree with the teacher who will provide support and when to check back after two practice opportunities; coordinate a brief update to the parent.",
            "Review the follow-up work with the teacher. Check wider class evidence before deciding whether a class-wide intervention is needed.",
        ],
    }
    if not needs_support:
        actions = {
            "parent": [f"Ask your child to explain one example from {topic} in their own words.",
                       "Encourage three new textbook questions, including one that applies the idea in a different situation.",
                       "Review any errors together and ask the teacher about a suitable next challenge."],
            "teacher": ["Use a few unfamiliar questions to check that the student can apply the recorded topics independently.",
                        "Ask for an explanation of the method and review any errors before assigning an extension task.",
                        "Check retention at the next classroom assessment and adjust the next learning goal accordingly."],
            "principal": ["Ask the teacher to confirm understanding through new questions and explanations.",
                          "Support suitable extension work where the teacher confirms readiness.",
                          "Review the next assessment with the teacher; use wider class evidence for school-level decisions."],
        }
    follow_ups = {
        "parent": "After two short practice sessions, note what your child can do without help and share remaining questions with the teacher.",
        "teacher": "Check new independent responses after practice, record the remaining errors and adapt support or extension work.",
        "principal": "At the agreed check-in, review the teacher's evidence of independent work and decide whether support should continue or change.",
    }
    roles = {}
    for role in actions:
        context = {"parent": "The next step is guided practice followed by a small independent check." if needs_support else "The next step is to check understanding with new examples.",
                   "teacher": "Use the marked work to choose the next teaching step; this score is not a diagnosis.",
                   "principal": "This is an individual learning review; it does not establish a class-wide or school-wide trend."}[role]
        roles[role] = {"headline": f"{name}'s learning report", "summary": f"{summary} {context}",
                       "strengths": strengths, "focus": focus, "actions": actions[role],
                       "follow_up": follow_ups[role], "evidence_note": evidence}
    return {"metrics": metrics, "insights": roles, "source": "rules", "model": "", "report_version": REPORT_VERSION}


def build_rules_report(records):
    return build_from_metrics(analyze_student(records[0]["student_id"], test_records=records))
