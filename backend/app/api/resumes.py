from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser
from app.schemas.resume import ResumeUploadResponse
from app.services import resume_service

router = APIRouter(tags=["resumes"])


# def, not async def: text extraction is blocking, synchronous work (Rules.md
# 4.3) — running it in an async route would block the event loop.
@router.post("/jobs/{job_id}/resumes", response_model=ResumeUploadResponse)
def upload_resumes(
    job_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    # default_factory=list, not File(...): an entirely absent "files" part
    # must reach resume_service's own NO_FILES_PROVIDED check (400) instead
    # of being rejected upstream by FastAPI's generic required-field 422 —
    # verified empirically, since a required File() field turns a fully
    # missing multipart part into REQUEST_VALIDATION_ERROR before this
    # function ever runs.
    files: list[UploadFile] = File(default_factory=list),
) -> ResumeUploadResponse:
    return resume_service.upload_resumes(db, job_id, files)
