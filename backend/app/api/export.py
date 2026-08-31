from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus
from app.database import get_db
from app.dependencies import CurrentUser
from app.services import export_service
from app.services.candidate_service import SortBy, SortOrder

router = APIRouter(tags=["export"])


@router.get("/jobs/{job_id}/export/csv")
# No response_model: this route streams generated CSV text, which a
# Pydantic model can't describe — mirrors
# candidates.get_candidate_resume_file's no-response_model FileResponse
# route. Same filter/sort query parameters as GET /candidates (Architecture.md
# 6.2: "accepts the same filters as /candidates"), minus job_id (fixed by
# the path) and page/page_size (an export is never paginated).
def export_candidates_csv(
    job_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_score: float | None = Query(default=None, ge=0, le=100),
    skills: list[str] | None = Query(default=None),
    min_experience: float | None = Query(default=None, ge=0),
    education_level: int | None = Query(default=None),
    status: ApplicationStatus | None = Query(default=None),
    sort_by: SortBy = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
) -> Response:
    export = export_service.export_candidates_csv(
        db,
        job_id,
        search=search,
        min_score=min_score,
        max_score=max_score,
        skills=skills,
        min_experience=min_experience,
        education_level=education_level,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return Response(
        content=export.content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )
