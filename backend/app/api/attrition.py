from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, pagination_params
from app.schemas.attrition import (
    AttritionBatchPredictRequest,
    AttritionBatchPredictResponse,
    AttritionPredictRequest,
    AttritionPredictResponse,
    EmployeeOut,
    ModelInfoResponse,
)
from app.schemas.common import Page
from app.services import attrition_service

router = APIRouter(prefix="/attrition", tags=["attrition"])


@router.post("/predict", response_model=AttritionPredictResponse)
def predict(
    payload: AttritionPredictRequest, current_user: CurrentUser, db: Session = Depends(get_db)
) -> AttritionPredictResponse:
    return attrition_service.predict(db, payload)


@router.post("/predict/batch", response_model=AttritionBatchPredictResponse)
def predict_batch(
    payload: AttritionBatchPredictRequest, current_user: CurrentUser, db: Session = Depends(get_db)
) -> AttritionBatchPredictResponse:
    return attrition_service.predict_batch(db, payload)


@router.get("/employees", response_model=Page[EmployeeOut])
def list_employees(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    pagination: dict = Depends(pagination_params),
) -> Page[EmployeeOut]:
    return attrition_service.list_employees(db, page=pagination["page"], page_size=pagination["page_size"])


@router.get("/model-info", response_model=ModelInfoResponse)
def model_info(current_user: CurrentUser) -> ModelInfoResponse:
    return attrition_service.get_model_info()
