# LLM interview-question human rating study — labelling package (Phase 13, F14.4)

**Status: rating sheet and generation tooling prepared. The 20 real questions could not be generated in this preparation session — see "Generation could not complete" below. Zero ratings exist. No score was assigned by this process.**

Per Phases.md Phase 13 / PRD F14.4: 20 real, LLM-generated,
resume-grounded interview questions, each rated 1–5 by a human on four
dimensions. This is the actual measure of question quality — distinct
from Phase 8's automated grounding filter (substring matching against
resume-derived anchors), which is a floor that rejects the most generic
outputs, not a substitute for human judgment of quality.

## The four rating dimensions

Rate each question 1 (worst) to 5 (best) on each of these, independently:

| Dimension | What it's asking |
|---|---|
| **relevance_1_to_5** | Is this a question a real interviewer would actually want to ask for *this specific job*? (Not just "is it a reasonable interview question in general" — does it fit this role.) |
| **specificity_1_to_5** | Does it drill into something concrete, or could it be asked of almost anyone with a similar job title? A question naming a real project, employer, or claimed metric from the resume should score high; a question that would work for any candidate should score low. |
| **technical_quality_1_to_5** | Is the question itself well-formed and technically sound — does it make sense, is it testing something real, is it free of factual or logical errors? |
| **resume_grounding_1_to_5** | Does the question correctly and clearly reference something that is actually true of this candidate's resume? (A question can be specific-sounding but still misread or misstate what the resume says — that should score low here even if it scores fine on specificity.) |

Use your own judgment for what a given integer score means beyond
"1 = worst, 5 = best" — no finer rubric than that is specified anywhere
in `PRD.md`/`Phases.md`.

## `llm_rating_sheet.csv` — column reference

`question_id, source_candidate, source_resume_file, job_title, job_id, generated_question, category, difficulty, relevance_1_to_5, specificity_1_to_5, technical_quality_1_to_5, resume_grounding_1_to_5, optional_human_notes`

The sheet contains 15 question rows with all four rating columns blank.
`category`/`difficulty` are the tags the LLM itself assigned to each
question (`technical`/`project`/`experience`/`skill_verification`/`behavioral`
and `easy`/`medium`/`hard` respectively, per F8.2/F8.3) — carried through
for context, not something to rate.

## Generation could not complete in this session

The plan was to generate the 20 questions through the real, already-built
production path — `POST /candidates/{id}/interview-questions` — exactly
as previously verified working in the Phase 8 grounding-filter fix
(`docs/EVALUATION.md`'s Phase 8 section: Aaron Whitfield 10/10 grounded,
Wei Chen 8/10, against the "Backend Software Engineer" job fixture from
`backend/tests/test_interview.py`). That job was recreated exactly, a
scratch database was set up (never touching `backend/hiring.db`), the
real backend was started against it, and three real `real_eval_set`
resumes were uploaded and requested (Aaron Whitfield, Wei Chen — the two
already-verified candidates — plus Maria Fernandez-Lopez as a new
third).

Every step up to the actual model call worked and is visible in the
server log: the real prompt was built correctly from the real uploaded
resume text and the real job description (see
`generation_attempt_2026-08-31.json` for the three `LLM_UNAVAILABLE`
responses this produced). The call itself failed because **this
preparation session's execution environment had no outbound network
access of any kind** — DNS resolution failed even for unrelated hosts
(`google.com`), not only for the configured provider (`api.groq.com`),
confirmed with direct `nslookup`/`curl` checks. This is an environment
limitation, not a problem with the code, the configuration, the API key,
or the data — `backend/.env`'s `OPENAI_API_KEY`/`OPENAI_BASE_URL` are
both set, and the exact same call previously succeeded in a different
session.

**Rather than fabricate question text to fill the sheet, generation was
left undone and is reported here as a shortfall**, per the instruction
not to fabricate, infer, simulate, or auto-fill anything the human
process depends on — a fabricated question would poison the one part of
Phase 13 that exists specifically to catch the model's output being
worse than it looks.

### To finish this step

Run `ml/llm_eval/generate_rating_candidates.py` from any machine/session
with real internet access to the configured LLM provider, against a
running instance of the real backend (see the script's own docstring for
exact steps — start the server, then run the script from the repo
root). It logs in as the seeded recruiter, creates the same "Backend
Software Engineer" job, uploads the same three real resumes, and calls
the real production endpoint for each — saving the full raw response to
`raw_generation_output.json`. From there, transcribe real generated
questions (verbatim — do not edit or paraphrase them) into
`llm_rating_sheet.csv`'s `generated_question` column, using as many of
the three candidates' real output as needed to reach exactly 20 rows,
leaving the four rating columns blank for the actual human rating pass.

Nothing about *why* generation should now succeed has changed since the
prior verified run — the grounding-filter fix that made real candidates
succeed (Memory.md, decision 51) is unmodified production code, still in
place.
