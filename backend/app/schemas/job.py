from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import JobSeniority, JobStatus, SkillType


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    min_experience_years: float = Field(ge=0)
    education_requirement: str = Field(min_length=1, max_length=80)
    seniority: JobSeniority
    location: str = Field(min_length=1, max_length=120)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    required_skills: list[str] | None = None
    min_experience_years: float | None = Field(default=None, ge=0)
    education_requirement: str | None = Field(default=None, min_length=1, max_length=80)
    seniority: JobSeniority | None = None
    location: str | None = Field(default=None, min_length=1, max_length=120)
    status: JobStatus | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "JobUpdate":
        # Every field above is Optional so PATCH can omit it, but none of the
        # underlying columns are nullable — omission must stay valid ("don't touch
        # this field") while an explicit null must not silently become a NOT NULL
        # constraint violation at commit time. model_fields_set is exactly the set
        # of keys the client actually sent, so this only rejects a field that was
        # present in the body AND null, never one that was simply left out.
        nulled = [field for field in self.model_fields_set if getattr(self, field) is None]
        if nulled:
            raise ValueError(f"Fields cannot be set to null: {', '.join(sorted(nulled))}")
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    required_skills: list[str]
    min_experience_years: float
    education_requirement: str
    seniority: JobSeniority
    location: str
    status: JobStatus
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class JobTopCandidate(BaseModel):
    candidate_id: int
    name: str | None
    final_fit_score: float


class JobDetailResponse(JobResponse):
    candidate_count: int
    average_fit_score: float | None
    top_candidate: JobTopCandidate | None


class SuggestedSkill(BaseModel):
    canonical: str
    type: SkillType


class SuggestedSkillsResponse(BaseModel):
    """Read-only (PRD F4.5). Nothing is written to required_skills — the
    recruiter reviews these and adds what they want via the existing
    PATCH /jobs/{id}. Mutating required_skills automatically would make it
    impossible to tell what the recruiter actually typed from what was
    inferred, and would re-add a skill the recruiter deliberately removed
    on the next description edit (project owner's explicit correction).
    """

    job_id: int
    suggested: list[SuggestedSkill]
