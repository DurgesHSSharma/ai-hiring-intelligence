from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, analytics_filters
from app.schemas.analytics import (
    AttritionAnalyticsResponse,
    OverviewResponse,
    ScoresResponse,
    SkillsResponse,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    filters: dict = Depends(analytics_filters),
) -> OverviewResponse:
    return analytics_service.get_overview(db, **filters)


@router.get("/skills", response_model=SkillsResponse)
def get_skills(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    filters: dict = Depends(analytics_filters),
) -> SkillsResponse:
    return analytics_service.get_skills(db, **filters)


@router.get("/scores", response_model=ScoresResponse)
def get_scores(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    filters: dict = Depends(analytics_filters),
) -> ScoresResponse:
    return analytics_service.get_scores(db, **filters)


@router.get("/attrition", response_model=AttritionAnalyticsResponse)
def get_attrition_analytics(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    filters: dict = Depends(analytics_filters),
) -> AttritionAnalyticsResponse:
    return analytics_service.get_attrition_analytics(db, **filters)
