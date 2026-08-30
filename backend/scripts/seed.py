"""Local dev convenience: one recruiter and two sample jobs, for exercising
/docs by hand. Run manually from backend/ with `python -m scripts.seed`.
Never imported by the application itself (Rules.md 4.1 — no business logic
at module import time).
"""
from app.core.enums import JobSeniority, JobStatus, UserRole
from app.core.security import hash_password
from app.database import SessionLocal
from app.models.job import Job
from app.models.user import User

SEED_EMAIL = "recruiter@example.com"
SEED_PASSWORD = "changeme123"


def run() -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == SEED_EMAIL).one_or_none() is not None:
            print(f"{SEED_EMAIL} already exists, skipping seed.")
            return

        user = User(
            name="Sample Recruiter",
            email=SEED_EMAIL,
            password_hash=hash_password(SEED_PASSWORD),
            role=UserRole.RECRUITER,
        )
        db.add(user)
        db.flush()

        db.add_all(
            [
                Job(
                    title="Backend Engineer",
                    description="Build and maintain REST APIs for the hiring platform.",
                    required_skills=["Python", "FastAPI", "PostgreSQL"],
                    min_experience_years=2.0,
                    education_requirement="Bachelor's",
                    seniority=JobSeniority.MID,
                    location="Remote",
                    status=JobStatus.OPEN,
                    created_by=user.id,
                ),
                Job(
                    title="Data Scientist",
                    description="Build the attrition and ranking models for the platform.",
                    required_skills=["Python", "scikit-learn", "pandas"],
                    min_experience_years=3.0,
                    education_requirement="Master's",
                    seniority=JobSeniority.SENIOR,
                    location="Bengaluru",
                    status=JobStatus.OPEN,
                    created_by=user.id,
                ),
            ]
        )
        db.commit()
        print(f"Seeded {SEED_EMAIL} (password: {SEED_PASSWORD}) and 2 jobs.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
