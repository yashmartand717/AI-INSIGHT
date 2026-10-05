from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Annotated[str, Field(min_length=1, max_length=200)]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Score = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Mark(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    record_id: Identifier
    student_id: Identifier
    student_name: Label
    class_name: Label
    section: Label
    subject: Label
    chapter: Label
    subtopic: str = Field(default="", max_length=300)
    total_questions: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    correct: Score
    attempted: Score | None = None
    test_date: str = Field(default="", max_length=30)
    previous_score_pct: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def scores(self):
        attempted = self.total_questions if self.attempted is None else self.attempted
        if not self.correct <= attempted <= self.total_questions:
            raise ValueError("Require 0 <= correct <= attempted <= total_questions")
        self.attempted = attempted
        return self


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    event_id: Annotated[str, Field(min_length=1, max_length=150)]
    records: list[Mark] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_records(self):
        ids = [r.record_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("record_id must be unique within the submission")
        students = {}
        for r in self.records:
            identity = (r.student_name, r.class_name, r.section)
            if r.student_id in students and students[r.student_id] != identity:
                raise ValueError("A student_id has conflicting name, class or section")
            students[r.student_id] = identity
        return self


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=1500)
    strengths: str = Field(min_length=1, max_length=1000)
    focus: str = Field(min_length=1, max_length=1000)
    actions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(min_length=1, max_length=3)


class InsightBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: Insight
    teacher: Insight
    principal: Insight
