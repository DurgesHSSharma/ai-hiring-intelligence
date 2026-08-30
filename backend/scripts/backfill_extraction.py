"""Applies field/skill extraction to existing candidates whose resume_text
was already stored before this code existed (Phase 4 candidates never got
Phase 5's extractor applied) or before a later extractor improvement —
extraction only runs automatically inside the upload pipeline
(resume_service.py), so nothing retroactively re-applies it without this.
Safe to re-run: it always recomputes from the stored resume_text and
overwrites, so running it twice, or after an extractor change, is
idempotent by construction rather than by a skip-if-already-done check.

Does NOT merge candidates. Dedupe-by-email (resume_service.py) only runs
at upload time; if backfilling two rows created before Phase 5 existed
happens to reveal they share an email, that's a data-integrity decision
for a human to make, not something this script resolves automatically —
it only reports it.

Run manually from backend/ with `python -m scripts.backfill_extraction`.
"""
from collections import Counter

from app.core.enums import ParseStatus
from app.database import SessionLocal
from app.ml.extraction.field_extractor import extract_all
from app.ml.skills.skill_matcher import match_skills
from app.models.candidate import Candidate
from app.models.candidate_skill import CandidateSkill


def run() -> None:
    db = SessionLocal()
    try:
        candidates = db.query(Candidate).filter(Candidate.parse_status == ParseStatus.PARSED).all()
        if not candidates:
            print("No parsed candidates found — nothing to backfill.")
            return

        for candidate in candidates:
            fields = extract_all(candidate.resume_text)
            candidate.name = fields.name
            candidate.email = fields.email
            candidate.phone = fields.phone
            candidate.education = fields.education
            candidate.education_level = fields.education_level
            candidate.experience_years = fields.experience_years
            candidate.projects = fields.projects
            candidate.certifications = fields.certifications

            db.query(CandidateSkill).filter(CandidateSkill.candidate_id == candidate.id).delete()
            for match in match_skills(candidate.resume_text):
                db.add(
                    CandidateSkill(
                        candidate_id=candidate.id,
                        skill_name=match.canonical,
                        skill_type=match.skill_type,
                        source=match.source,
                    )
                )

        db.commit()
        print(f"Backfilled extraction for {len(candidates)} parsed candidate(s).")

        email_counts = Counter(c.email for c in candidates if c.email is not None)
        duplicates = {email: count for email, count in email_counts.items() if count > 1}
        if duplicates:
            print(
                f"\nWARNING: {len(duplicates)} email(s) now appear on more than one "
                "candidate row (backfill does not merge — review manually):"
            )
            for email, count in duplicates.items():
                print(f"  {email}: {count} candidates")
    finally:
        db.close()


if __name__ == "__main__":
    run()
