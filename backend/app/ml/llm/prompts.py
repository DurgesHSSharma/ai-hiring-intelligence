"""Interview-question generation prompt templates (Rules.md 4.7 — named
constants, never inline in a service function). Every prompt demands
strict JSON with no prose and no code fences (Rules.md 4.7, F8.5).

Prompt changes are recorded in Memory.md with the reason (Rules.md 4.7) —
they change output quality invisibly.
"""

QUESTION_GENERATION_SYSTEM = (
    "You are an experienced technical recruiter preparing interview questions "
    "for a specific candidate and a specific job opening. Every question you "
    "write must reference a concrete detail from the candidate's own resume — "
    "a real project, technology, role, or claim they made — never a generic "
    "question that could be asked of any candidate. Respond with strict JSON "
    "only: no prose before or after the JSON, no markdown code fences, no "
    "explanation. Return nothing except the JSON object described below."
)

QUESTION_GENERATION_TEMPLATE = """Generate {count} interview questions for this candidate, for this job.

## Job
Title: {job_title}
Seniority: {job_seniority}
Required skills: {required_skills}
Minimum experience: {min_experience_years} years
Description:
{job_description}

## Candidate profile
Matched skills (already on the required list): {matched_skills}
Missing skills (required but not found on this candidate): {missing_skills}
Experience: {experience_years} years
Education: {education}
Projects listed:
{projects}
Certifications listed:
{certifications}

## Candidate's resume (verbatim, extracted text)
{resume_text}

## Instructions
- Write {count} questions, covering a mix of categories: technical, project, experience, skill_verification, behavioral.
- Assign each question a difficulty: easy, medium, or hard.
- Every question must name something specific and real from the resume above — a project name, a technology, an employer, a claimed number, a specific responsibility. Never ask something that could be asked of any candidate for any job ("Tell me about yourself", "Why do you want this job", "What are your strengths").
- For each question, give a one-sentence rationale naming which resume detail prompted it.
- If the candidate is missing a required skill, you may include a skill_verification question probing related experience.
- Return ONLY this JSON object, no other text:

{{
  "questions": [
    {{"question": "...", "category": "technical", "difficulty": "medium", "rationale": "..."}}
  ]
}}
"""

REPAIR_INSTRUCTION_TEMPLATE = (
    "Your previous response could not be used: {error}\n"
    "Return ONLY a single valid JSON object matching this exact shape, with "
    "no prose, no markdown, and no code fences:\n"
    '{{"questions": [{{"question": "...", "category": "technical", '
    '"difficulty": "medium", "rationale": "..."}}]}}'
)
