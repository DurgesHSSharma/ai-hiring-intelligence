"""SQLite does not enforce foreign keys unless PRAGMA foreign_keys=ON is
issued per connection — without it, every ondelete= in Architecture.md 5.2
is a silent no-op in development. This proves the listener in database.py
(and its copy in conftest.py's db_session fixture) actually has that effect.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import ApplicationStatus, RiskLevel
from app.models.application import Application
from app.models.attrition_prediction import AttritionPrediction
from app.models.employee import Employee


def test_foreign_key_enforcement_blocks_orphan_insert(db_session):
    orphan = Application(candidate_id=99999, job_id=99999, status=ApplicationStatus.NEW)
    db_session.add(orphan)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_employee_delete_cascades_to_attrition_predictions(db_session):
    """Same empirical proof as the job/candidate cascade tests: create an
    employee and a prediction, delete the employee, confirm the prediction
    is gone. Relies on Employee.attrition_predictions' passive_deletes=True
    (models/employee.py) actually reaching the FK's ondelete="CASCADE"
    instead of the ORM trying to null employee_id itself first.
    """
    employee = Employee(
        age=30,
        department="Engineering",
        job_level=2,
        monthly_income=5000.0,
        years_at_company=3,
        years_since_last_promotion=1,
        years_with_curr_manager=2,
        total_working_years=8,
        job_satisfaction=3,
        environment_satisfaction=3,
        relationship_satisfaction=3,
        performance_rating=3,
        overtime=False,
        business_travel="rarely",
        distance_from_home=5,
        percent_salary_hike=10.0,
        stock_option_level=1,
    )
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)

    prediction = AttritionPrediction(
        employee_id=employee.id,
        probability=0.5,
        risk_level=RiskLevel.MEDIUM,
        model_version="test-v1",
        prediction_date=datetime.now(timezone.utc),
    )
    db_session.add(prediction)
    db_session.commit()

    db_session.delete(employee)
    db_session.commit()

    assert db_session.query(AttritionPrediction).filter_by(employee_id=employee.id).count() == 0
