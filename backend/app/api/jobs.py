from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AdminUser, CurrentUser, pagination_params
from app.schemas.common import DeletedResponse, Page
from app.schemas.job import (
    JobCreate,
    JobDetailResponse,
    JobResponse,
    JobUpdate,
    SuggestedSkillsResponse,
)
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobResponse])
def list_jobs(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    # Aliased so the Python-side name never collides with the module-level
    # `status` import used below for status_code=status.HTTP_201_CREATED.
    status_filter: Literal["open", "closed", "all"] = Query(default="open", alias="status"),
    pagination: dict = Depends(pagination_params),
) -> Page[JobResponse]:
    return job_service.list_jobs(
        db,
        search=search,
        status_filter=status_filter,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate, current_user: CurrentUser, db: Session = Depends(get_db)
) -> JobResponse:
    return job_service.create_job(db, payload, current_user)


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: int, current_user: CurrentUser, db: Session = Depends(get_db)) -> JobDetailResponse:
    return job_service.get_job_detail(db, job_id)


@router.get("/{job_id}/suggested-skills", response_model=SuggestedSkillsResponse)
def get_suggested_skills(
    job_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> SuggestedSkillsResponse:
    return job_service.get_suggested_skills(db, job_id)


@router.patch("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: int, payload: JobUpdate, current_user: CurrentUser, db: Session = Depends(get_db)
) -> JobResponse:
    return job_service.update_job(db, job_id, payload)


@router.delete("/{job_id}", response_model=DeletedResponse)
def delete_job(job_id: int, current_user: AdminUser, db: Session = Depends(get_db)) -> DeletedResponse:
    return job_service.delete_job(db, job_id)
