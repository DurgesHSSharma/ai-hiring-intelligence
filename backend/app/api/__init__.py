from fastapi import APIRouter

from app.api import attrition, auth, candidates, health, interview, jobs, resumes, scoring

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(jobs.router)
api_router.include_router(candidates.router)
api_router.include_router(resumes.router)
api_router.include_router(scoring.router)
api_router.include_router(interview.router)
api_router.include_router(attrition.router)
