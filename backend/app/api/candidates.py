from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus
from app.database import get_db
from app.dependencies import CurrentUser, pagination_params
from app.schemas.candidate import (
    ApplicationResponse,
    ApplicationStatusUpdate,
    CandidateDetailResponse,
    CandidateListItem,
)
from app.schemas.common import DeletedResponse, Page
from app.services import candidate_service
from app.services.candidate_service import SortBy, SortOrder

# Two resources (candidates, applications) share this module: Architecture.md 3's
# folder tree has no api/applications.py, and groups PATCH /applications/{id} under
# the "Candidates" table section — so no shared prefix, full paths per route.
router = APIRouter(tags=["candidates"])


@router.get("/candidates", response_model=Page[CandidateListItem])
def list_candidates(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    job_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_score: float | None = Query(default=None, ge=0, le=100),
    skills: list[str] | None = Query(default=None),
    min_experience: float | None = Query(default=None, ge=0),
    education_level: int | None = Query(default=None),
    status: ApplicationStatus | None = Query(default=None),
    sort_by: SortBy = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
    pagination: dict = Depends(pagination_params),
) -> Page[CandidateListItem]:
    return candidate_service.list_candidates(
        db,
        job_id=job_id,
        search=search,
        min_score=min_score,
        max_score=max_score,
        skills=skills,
        min_experience=min_experience,
        education_level=education_level,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailResponse)
def get_candidate(
    candidate_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> CandidateDetailResponse:
    return candidate_service.get_candidate_detail(db, candidate_id)


@router.get("/candidates/{candidate_id}/resume-file")
# No response_model: this route streams a binary file, which a Pydantic
# model can't describe. FileResponse sets an explicit media_type (never
# guessed from the extension) and filename=resume_filename so the download
# shows the candidate's original name, not the stored UUID.
def get_candidate_resume_file(
    candidate_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> FileResponse:
    resume_file = candidate_service.get_resume_file(db, candidate_id)
    return FileResponse(resume_file.path, media_type=resume_file.media_type, filename=resume_file.display_filename)


@router.delete("/candidates/{candidate_id}", response_model=DeletedResponse)
def delete_candidate(
    candidate_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> DeletedResponse:
    return candidate_service.delete_candidate(db, candidate_id)


@router.patch("/applications/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: int,
    payload: ApplicationStatusUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    return candidate_service.update_application_status(db, application_id, payload.status)
