# Evaluation

Real numbers only, produced by a script that can be re-run, or by a
recorded human rating sheet (Rules.md §1.3, §8). No number below is
estimated, rounded upward, or presented selectively.

---

## Phase 5 — Field extraction (PRD F3.5)

### Two evaluation sets, not one

There are two separate 30-ish-resume sets in this repository, and they
serve different purposes. Conflating them would produce a number that
looks like a measurement but isn't one.

**`backend/tests/fixtures/regression_eval_set/`** — 30 synthetic resumes,
generated from structured data, with labels computed independently from
that same structured data. This is a **regression suite only**
(`backend/tests/test_regression_eval_set.py`). It proves the extractor
keeps behaving consistently as `field_extractor.py`/`skill_matcher.py`
change. **Its numbers are never used as an accuracy measurement below** —
a synthetic generator and the extractor it's tested against inevitably
share the same assumptions about date formats and section-heading
vocabulary, so a resume built to be extractable by construction cannot
honestly measure how well the extractor handles resumes it didn't help
write. This was an explicit correction from the project owner during
Phase 5 planning, made after `real_resume.pdf` (Phase 4) had already
demonstrated exactly this trap at the text-extraction layer: a synthetic
fixture that looks like a resume can still fail to exercise the variation
a real one contains.

**`backend/tests/fixtures/real_eval_set/`** — resumes built from real
public templates (Word/Google Docs) with invented personal details, in
varied layouts, supplied and hand-labelled by the project owner
independently of this codebase. **This is the set the numbers below come
from**, via `python -m scripts.evaluate_field_extraction` (run from
`backend/`). Ground truth here is independent by construction: the
project owner labelled these resumes without reference to what the
extractor produces.

### Grading methodology

| Field | Correct when |
|---|---|
| Name | Case-insensitive exact match against the label. |
| Email | Exact match against the label. |
| Phone | Both sides normalized to digits-only before comparing — the extractor preserves the resume's original punctuation, which isn't a meaningful thing to grade against directly. |
| Education | The extracted ordinal ladder level (`data/education.json`) matches the labelled level — not a string match, since "B.S." and "Bachelor of Science" are the same fact. |
| Experience (years) | Extractor output is not `None` and is within **±1.0 year** of the labelled value. A labelled `None` (no usable dates on the resume) only counts as correct against an extractor `None`. |

Any labelled resume tagged `layout: two_column` that misses on any field
is flagged automatically by the evaluation script — this is the concrete,
evidence-based candidate list for Phase 13's two-column PDF work (see
Known limitations below and Memory.md decision 27), not a manually
curated guess.

### Results — first measurement (pre-fix, unmodified extractor)

**First honest measurement, recorded before any tuning**, from `python -m
scripts.evaluate_field_extraction` against `real_eval_set/` (12 resumes:
7 PDF, 5 DOCX, 4 two-column, supplied and hand-labelled by the project
owner independently of this codebase). Raw script output, unedited:

```
Field extraction accuracy — real evaluation set, n=12

  name                   9/12  (75.0%)
  email                 12/12  (100.0%)
  phone                 12/12  (100.0%)
  education_level        8/12  (66.7%)
  experience_years       9/12  (75.0%)

3 two-column resume(s) had at least one field miss — possible column-corruption cases for Phase 13:
  resume_003.pdf: missed name, education_level, experience_years
  resume_008.pdf: missed education_level, experience_years
  resume_011.docx: missed education_level
```

| Field | Target (PRD F3.5) | Measured | n | Met? |
|---|---|---|---|---|
| Email | ≥ 95% | **100.0%** (12/12) | 12 | Yes |
| Phone | ≥ 90% | **100.0%** (12/12) | 12 | Yes |
| Name | ≥ 75% | **75.0%** (9/12) | 12 | Yes (exactly at target) |
| Education | ≥ 80% | **66.7%** (8/12) | 12 | **No** |
| Experience (years) | ≥ 70% | **75.0%** (9/12) | 12 | Yes |

n=12 is small — one resume is worth 8.3 percentage points, so "75.0%"
and "66.7%" should be read as "9 right, 3 wrong" and "8 right, 4 wrong,"
not as precise rates. No number here has been rounded up, adjusted, or
had the extractor tuned against it; this is the first run.

### Every failure, by field, with the verified reason

Each reason below was confirmed by direct inspection of the resume's
cleaned text and the extractor's intermediate output (section-heading
detection, matched date ranges, parsed intervals) — not inferred from
the mismatch alone.

**Name (3 misses — resume_003, resume_007, resume_010):**

| Resume | Expected | Got | Reason |
|---|---|---|---|
| resume_003.pdf (two_column) | Wei Chen | "Wei Chen EXPERIENCE" | Two-column layout welds the candidate's name to the `EXPERIENCE` heading from the adjacent column on the same visual row (`pdfplumber`'s y-position text join) — the same class of corruption as Phase 5's own regression fixtures, not a new failure mode. |
| resume_007.pdf (single_column) | Nkechi Obi | "Dr. Nkechi Obi" | The name heuristic doesn't strip an honorific prefix. Not previously documented — no regression fixture carried a titled name. |
| resume_010.pdf (single_column) | Ravindran | "Network Support Specialist" | The first-line heuristic requires 2-4 capitalized words and structurally cannot match a single-word name, so it skips the real name entirely — then wrongly accepts the job-title line below it, which is *also* syntactically 2-4 capitalized words, before ever reaching the spaCy fallback. Not previously documented — no regression fixture carried a single-word name. |

**Education (4 misses — resume_003, resume_008, resume_010, resume_011):**

| Resume | Expected | Got | Reason |
|---|---|---|---|
| resume_003.pdf (two_column) | bachelor | None | Vocabulary gap: `"BA Graphic Communication"` — bare `BA` with no periods and not followed by `"in"` — matches none of the current bachelor patterns (`"b.a."` needs periods, `"ba in"` needs the word "in" immediately after). Confirmed independent of the layout: the EDUCATION section itself was located correctly. |
| resume_008.pdf (two_column) | bachelor | None | Vocabulary gap: `"B.Eng."` isn't a listed pattern (only `"b.e."` and `"bachelor of engineering"` are). |
| resume_010.pdf (single_column) | associate | None | Vocabulary gap: `"Diploma in Computer Networking"` — the word "diploma" doesn't appear in any ladder pattern. |
| resume_011.docx (two_column) | high_school | None | Vocabulary/localization gap: `"Diploma di Maturita"` (Italian secondary-school diploma) has no English-language equivalent in the current pattern list. |

None of the four education misses is a two-column artifact by cause — three of the four resumes happen to be tagged two-column, but in all four cases the EDUCATION section was located and scanned correctly; the pattern list itself simply doesn't cover the phrasing. This is the same class of gap as the `B.Des`/`Associate of Applied Science` gaps found and fixed during Phase 5 development — the ladder covers common English degree phrasing, not an exhaustive or multilingual list.

**Experience years (3 misses — resume_003, resume_007, resume_008):**

| Resume | Expected | Got | Reason |
|---|---|---|---|
| resume_003.pdf (two_column) | 4.7 | 9.8 | The candidate's name and the `EXPERIENCE` heading are welded together (`"Wei Chen EXPERIENCE"`, same corruption as its name miss above), so no line matches an experience heading exactly and section-scoping fails. The fallback scans the whole resume and picks up the EDUCATION section's own `"2014-2018"` attendance range as if it were a job, adding 60 months (5.0 years) that don't belong. |
| resume_007.pdf (single_column) | 11.0 | 21.0 | The experience heading on this resume is `"APPOINTMENTS"`, which isn't in the recognized heading list (`experience`/`work experience`/`professional experience`/`employment history`/`work history`/`employment`). Section-scoping fails for a purely vocabulary reason — no column corruption is involved. The fallback scans the whole resume; the two real appointment ranges (2018-2024, 2014-2018) and all three listed degrees' date ranges (2010-2014, 2008-2010, 2004-2008) happen to chain end-to-end with no gaps, so they merge into one continuous 2004-2024 span — 21.0 years, exactly. |
| resume_008.pdf (two_column) | 5.8 | 10.2 | Same mechanism as resume_003: the heading reads `"CONTACT EXPERIENCE"` (the sidebar's `CONTACT` welded onto `EXPERIENCE`), section-scoping fails, and the fallback picks up the EDUCATION section's `"2011-2015"` range. See the dedicated check below — this is confirmed **not** a gap-bridging defect. |

### Specifically checked, as requested

**resume_005 — no dates anywhere, must return `None`, not `0.0`.** Confirmed by direct inspection: the EXPERIENCE section is located correctly, zero date-range matches are found in it, and `extract_experience_years` returns `None`. This resume did not miss on any field. **No defect — the code does exactly what it's supposed to do here.**

**resume_008 — genuine 30-month gap (Mar 2018 - Sep 2020), must not be bridged.** The measured total is 10.2 years, not the ~8.4 years that bridging the two real jobs into one continuous span would produce. Traced through the actual month-index arithmetic: the two real job intervals (Apr 2015 - Mar 2018, Sep 2020 - Aug 2023) are parsed correctly, and the merge step correctly leaves a 30-month break between them — they are **not** merged into each other. **The interval-merge algorithm is not the defect.** The 10.2 figure comes entirely from a third interval that should never have reached the merge step at all: the EDUCATION section's `"2011-2015"` (a side effect of the same heading-corruption described above), which happens to overlap the *first* real job's start (2015) and so correctly, mechanically merges with it under the overlap rule — extending that job's start back to Jan 2011 and adding 51 months that don't belong. Everything downstream of "which intervals are candidates" behaved correctly; the input to that step was wrong.

### What these two checks establish

Both specific concerns were about whether a fundamental piece of the experience-years logic was broken (the `None`-vs-`0.0` guarantee, and the gap/overlap merge rule). Neither was. Every experience-years miss in this set traces to the same single upstream cause — **EXPERIENCE section-heading detection failing** (either because a two-column layout welds the heading to something else, or because the resume uses heading vocabulary not on the recognized list), which triggers the already-documented whole-resume fallback and lets an EDUCATION date range in. The merge arithmetic downstream of that has been exercised on real, messy, human-written resumes now (not just synthetic ones) and has not produced a single incorrect result.

### Fixes applied after the first measurement

Four targeted additions to existing vocabulary lists, no logic changes, plus one deliberate failure-mode change. Each justified below as a general improvement — not a patch for these twelve files — per the project owner's explicit instruction that a fix without that justification doesn't get made.

1. **`data/education.json`: added bare `"ba"`/`"bs"` (word-boundary-safe, so still not matched mid-word), `"b.eng."`, and `"diploma"`.** *General because:* these are standard, widely-used English-language degree abbreviations in routine use on real resumes everywhere — not phrases invented to match this corpus. (Notably, three of the four resumes that triggered this fix were different templates from different regions, which is itself evidence the gap wasn't corpus-specific.)
2. **`field_extractor.py`: added `"appointments"`, `"positions"`, `"career history"` to the recognized EXPERIENCE heading list.** *General because:* `"Appointments"` is the standard heading on academic/clinical CVs as a genre, not a quirk of `resume_007`; `"Positions"` and `"Career History"` are common alternate headings on general and executive resume templates, added proactively (per the instruction to check the list, not because they were observed in this corpus).
3. **`field_extractor.py`: strip a leading honorific (`Dr.`, `Prof.`, `Mr.`, `Ms.`, `Mrs.`, `Er.`) before the name heuristic's shape check.** *General because:* this is a small, fixed, universally-recognized set of titles that can prefix any resume's name, not specific to `resume_007`'s "Dr." — and the regex only strips when followed by whitespace, so it cannot misfire on a name that happens to start with the same letters (verified: "Erika" is untouched).
4. **`"Diploma di Maturita"` — deliberately NOT added.** Could not defend it as a general improvement rather than a one-off patch for `resume_011`: fixing it properly would mean committing to genuine multi-language degree coverage (which languages, how many terms, whether diacritics need normalizing), which is a real scoping decision, not a one-line addition. Left as a documented gap.
5. **Not a vocabulary fix — a failure-mode change, per explicit instruction:** the first-line name heuristic no longer keeps scanning subsequent lines after its first real candidate line fails the name-shape check; it now stops and falls through to the spaCy fallback instead. *General because:* a job title being exactly as "2-4 capitalized words"-shaped as a real name isn't specific to `resume_010` — any resume where the true name doesn't match that shape (a single word, a hyphenated or unusual format) was equally exposed to this failure mode before.

### Results — post-fix measurement

```
Field extraction accuracy — real evaluation set, n=12

  name                  10/12  (83.3%)
  email                 12/12  (100.0%)
  phone                 12/12  (100.0%)
  education_level       11/12  (91.7%)
  experience_years      10/12  (83.3%)

3 two-column resume(s) had at least one field miss — possible column-corruption cases for Phase 13:
  resume_003.pdf: missed name, experience_years
  resume_008.pdf: missed experience_years
  resume_011.docx: missed education_level
```

| Field | Target | Before | After | n | Met after? |
|---|---|---|---|---|---|
| Email | ≥ 95% | 100.0% (12/12) | 100.0% (12/12) | 12 | Yes (unchanged) |
| Phone | ≥ 90% | 100.0% (12/12) | 100.0% (12/12) | 12 | Yes (unchanged) |
| Name | ≥ 75% | 75.0% (9/12) | **83.3%** (10/12) | 12 | Yes |
| Education | ≥ 80% | 66.7% (8/12) | **91.7%** (11/12) | 12 | Yes |
| Experience (years) | ≥ 70% | 75.0% (9/12) | **83.3%** (10/12) | 12 | Yes |

All five targets are now met on this 12-resume set. `resume_003`, `resume_008` (two-column heading corruption, deferred to Phase 13, not patched) and `resume_011` (the skipped non-English education term) account for every remaining miss.

### Two side effects found while re-measuring — reported, not hidden

Neither of these is what was asked for; both were found by re-running the diagnostic in full rather than trusting the aggregate numbers, and both matter more than the count alone shows.

**`resume_011`'s education field went from a safe `None` to a confidently wrong guess.** Before the fix, `"Diploma di Maturita"` matched nothing and correctly returned `None` — a miss, but an honest one. After adding bare `"diploma"` (fix #1, for `resume_010`'s legitimate `"Diploma in Computer Networking"`), the same word inside `"Diploma di Maturita"` now matches too, and the resume is scored as `associate` (level 2) instead of the true `high_school` (level 1). **The pass/fail count for this resume doesn't change — it was a miss before and is a miss after — but the failure mode got worse**, exactly the class of problem this project has repeatedly treated as more serious than a miss (the whole reason `extract_experience_years` returns `None` instead of `0.0`, and the whole reason for fix #5 above). This is a direct, real tradeoff of a single-word vocabulary addition and is reported here rather than quietly accepted because the aggregate number looked fine.

**`resume_010`'s name still isn't `None` — it's now `"Maintained"`, a different wrong answer from spaCy.** Fix #5 worked exactly as specified: verified directly that the heuristic itself now stops after `"Ravindran"` fails its shape check, rather than continuing on to accept `"Network Support Specialist"`. But `extract_name()` doesn't stop there — it falls through to the spaCy NER fallback, and on this resume's text, `en_core_web_sm` independently mis-tags the word `"Maintained"` (capitalized at the start of a bulleted sentence: `"• Maintained the escalation runbook..."`) as a `PERSON` entity. Confirmed by running spaCy on the exact text: it does not find `"Ravindran"` as `PERSON` anywhere in the first 500 characters, and does tag `"Maintained"`. This is a pre-existing limitation of the small spaCy model's NER accuracy on resume bullet fragments — not introduced by this fix, and not something the heuristic-layer change could have addressed — but it was previously invisible because the old (buggy) heuristic always "succeeded" first and never let a resume like this one reach the fallback. The instruction to fix the failure mode was carried out correctly at the layer it targeted; the overall function still doesn't achieve the intended `None` on this specific resume, for a different, independent reason one layer down.

### Known limitations

Documented here per the project owner's explicit instruction, not left
only as code comments.

- **Dictionary/keyword terms that are also common English words produce
  false positives.** Confirmed concretely during development: the skill
  alias `"go"` (the Go programming language) matches inside ordinary
  prose like "Time to go home," because word-boundary matching prevents
  cross-token false positives (e.g. `R` inside `React`, `Go` inside
  `Google`) but cannot disambiguate word *sense*. The same class of risk
  applies to a smaller degree to a few other short skill names that
  double as ordinary words (`Spring`, `Swift`, `R`). This is an inherent
  limit of dictionary-based matching, not a defect in the boundary regex
  itself — the boundary mechanism was verified against 13 explicit cases
  (see `skill_matcher.py`'s module docstring and `test_skill_matcher.py`)
  and behaves exactly as designed in all of them.
- **`"js"`/`"ts"` are deliberately not aliases** for JavaScript/TypeScript,
  discovered empirically while building the dictionary: the boundary
  regex doesn't block on `.`, so bare `"js"`/`"ts"` would match inside
  `Node.js`, `Vue.js`, `Express.js`, `Next.js`, `Ember.js`, or a file
  mention like `index.ts` — falsely registering JavaScript/TypeScript for
  a mention of an unrelated framework or file. `"JavaScript"`/
  `"TypeScript"` written in full still match normally; a resume that only
  ever writes the bare two-letter shorthand for either will be missed.
- **Experience-years extraction falls back to scanning the whole resume**
  when no recognized EXPERIENCE-family heading is found, and that
  fallback can pick up an unrelated date range from elsewhere on the
  resume. Confirmed on real data: this was the root cause of all three
  original experience-years misses on the real evaluation set. The
  heading-vocabulary-gap trigger (`resume_007`'s `"APPOINTMENTS"`) is
  fixed — `"appointments"`/`"positions"`/`"career history"` are now
  recognized. The **two-column heading-corruption trigger is not fixed**
  and remains the cause of both remaining experience-years misses
  (`resume_003`: `"Wei Chen EXPERIENCE"`; `resume_008`:
  `"CONTACT EXPERIENCE"` — a two-column layout welding the heading line
  to adjacent text so exact-line matching can't recognize it). This is
  entangled with the column-splitting problem deferred to Phase 13
  (Memory.md decision 27) and was deliberately left alone rather than
  patched around. A resume with a recognized, uncorrupted EXPERIENCE
  heading is scoped to that section only and doesn't carry this risk —
  confirmed on 10 of the 12 real resumes.
- **Two-column PDF layouts corrupt some fields but not others**, and can
  corrupt a section *heading line* itself (not just body text like a
  name). Email and phone extracted correctly on every two-column resume
  in the real set (4/4 each) both before and after this round's fixes.
  Of the 4 two-column resumes, 3 still have a miss: `resume_003`
  (name, experience-years) and `resume_008` (experience-years) via the
  heading-corruption mechanism above; `resume_011` (education) via an
  unrelated vocabulary gap that happens to sit on a two-column resume —
  see below, this one is not a column-corruption case. Column-splitting
  itself remains formally deferred to Phase 13; these three are the
  concrete carry-over for that phase.
- **The name heuristic no longer accepts a same-shaped line when its
  real candidate fails the shape check** (fixed: it now stops and falls
  through to the spaCy fallback instead of continuing to scan), **and no
  longer keeps an unstripped honorific prefix** (fixed: `"Dr."`/`"Prof."`/
  `"Mr."`/`"Ms."`/`"Mrs."`/`"Er."` are stripped before the check runs).
  **Still cannot recognize a single-word name** (`resume_010`'s
  `"Ravindran"`) — left deliberately unfixed, since the first-line
  pattern requiring 2-4 capitalized words is what makes it reliable for
  the common case, and loosening it risks new false positives. The
  failure mode for this specific gap changed as intended (no longer a
  confident wrong guess from the heuristic) but did not reach `None`:
  `resume_010`'s name now comes from the spaCy fallback misfiring on an
  unrelated word (see the side-effects section above) — a second,
  independent limitation (spaCy's small-model NER accuracy on bullet
  fragments) that the heuristic fix exposed rather than caused.
- **A single-word vocabulary addition can trade a safe absence for a
  wrong guess**, confirmed concretely this round: adding bare `"diploma"`
  fixed `resume_010`'s `"Diploma in Computer Networking"` but also now
  matches inside `resume_011`'s Italian `"Diploma di Maturita"`,
  producing `associate` instead of the true `high_school` — previously
  this resume correctly returned `None`. The pass/fail count for
  `resume_011` is unchanged (miss before, miss after), but the failure
  degraded from absence to a wrong answer. No fix applied for this
  specific collision — doing so would mean either reverting a fix that
  correctly serves a different, legitimate resume, or engineering
  something more targeted than "diploma" alone, which risks the same
  overfitting problem this round of fixes was explicitly trying to avoid.
- **Phone extraction is format-agnostic by digit count (7-15 digits, the
  E.164 range), not by grouping shape** — deliberately, so an Indian
  mobile number written "98765 43210" (5+5) is not missed the way a
  hardcoded "3-3-4" US grouping would miss it. Confirmed on the real set:
  12/12 phones extracted correctly, across US, Indian, Japanese, Nigerian,
  Swedish, Italian, Norwegian, and Spanish formats. The theoretical
  tradeoff (a ZIP+4 or similarly-shaped digit run false-positiving) has
  still not been observed in either evaluation set.
- **The education ladder (`data/education.json`) covers common English
  degree phrasings, not an exhaustive or multilingual list.** Five gaps
  have now been found and fixed across two sessions (`"Associate of
  Applied Science"`, `"B.Des"`, bare `"BA"`/`"BS"`, `"B.Eng."`,
  `"Diploma"`). **Deliberately left unfixed:** non-English degree names
  (`resume_011`'s Italian `"Diploma di Maturita"` is the one confirmed
  case) — genuine multi-language coverage is a real scoping decision
  (which languages, how many terms, diacritic handling), not a one-line
  addition, and adding just this one term would have been a patch for
  this corpus specifically rather than a general improvement. A resume
  in a language other than English currently extracts education as
  `None` (or, per the new limitation above, occasionally a wrong ordinal
  level if a fixed English term happens to appear as a substring) rather
  than being handled correctly.

---

## Phase 6 — education.json touched again, re-measured

Phase 6 (TF-IDF ranking, composite fit score) needed one ladder level for
each side of the education comparison: the candidate's extracted
`education_level` (already built in Phase 5) and the *job's* required
level, derived by running the same `extract_education()` against
`job.education_requirement`. That field is free text (e.g. `"Bachelor's"`,
the literal value in `backend/scripts/seed.py` and most job fixtures) —
terser than the resume phrasing the ladder was built for, and it matched
nothing, returning an unresolvable requirement for the seed data as-is.

Added two bare possessive/plural forms per level, narrowly scoped to what
the seed data and typical one-line job-requirement phrasing actually need:
`"bachelor's"`/`"bachelors"` (bachelor level) and `"master's"`/`"masters"`
(master level). Deliberately did **not** add `"associate's"`/`"associates"`
or bare `"high school"` — no concrete driving case for either (unlike
bachelor's/master's, nothing in the seed data or fixtures needs them), and
`"associates"` in particular carries real collision risk with a job title
("Senior Associate") or a company name. Same one-line-justification
discipline as the Phase 5 fix round: added what a concrete case demands,
not what looked symmetric.

Re-ran `python -m scripts.evaluate_field_extraction` against the same
12-resume `real_eval_set/` immediately after, since this touches the exact
dictionary that measurement depends on:

| Field | Before (Phase 5 post-fix) | After (Phase 6) |
|---|---|---|
| name | 83.3% (10/12) | 83.3% (10/12) |
| email | 100% (12/12) | 100% (12/12) |
| phone | 100% (12/12) | 100% (12/12) |
| education_level | 91.7% (11/12) | 91.7% (11/12) |
| experience_years | 83.3% (10/12) | 83.3% (10/12) |

No change. The remaining `resume_011` education miss is the same
already-documented, deliberately-unfixed non-English gap (`"Diploma di
Maturita"`) — unaffected, since neither new pattern appears in that text.

## Phase 6 — ranking sensibility (qualitative, not a numeric metric)

Phase 6's acceptance criterion is a manual sensibility check ("the ordering
is sensible on manual inspection of the top and bottom three"), not a
numeric ranking metric — there is no relevance-labelled ground truth for
ranking yet (that would need recruiters' actual judgments of which
candidates suit which jobs, which does not exist for this project). A real
ranking-quality metric (Precision@K, NDCG) is out of scope until such
labels exist — see `Phases.md` Phase 13.

Ran the full upload → extract → score pipeline (no shortcuts, no hand-set
test values) against a real "Backend Software Engineer" posting
(`required_skills: ["Python", "SQL", "AWS", "PostgreSQL", "Kubernetes"]`,
`min_experience_years: 3.0`) and all 12 `real_eval_set/` resumes — a
deliberately mixed set spanning backend/data engineering, product design,
logistics, mechanical engineering, customer success, public health
research, QA, finance, network support, and retail. Full ranked list, top
3 and bottom 3 in full detail, are in `Memory.md`'s Phase 6 section.

Summary: the two candidates with the closest genuine skill/domain overlap
(a backend engineer matching 3/5 required skills, a data engineer matching
3/5 with different but adjacent tooling) ranked highest; every candidate
from a completely unrelated field (retail, logistics, mechanical
engineering, customer success, public health, finance) ranked at the
bottom with 0% skill match. The ordering is sensible.

---

## Phase 7 — TF-IDF vs. embedding ranking, and the semantic skill-match threshold

### Methodology

Same qualitative standard as Phase 6 — no relevance-labelled ground truth
for ranking exists yet, so this is a manual comparison of two real
rankings on the same inputs, not a numeric metric (Precision@K/NDCG
against both methods is Phase 13 territory, once `ml/ranking_eval/`'s
labelled set exists).

Ran the real upload → extract → score pipeline (`TestClient` against a
fresh in-memory database — the real `backend/hiring.db` was never opened
by this run, confirmed by checking it before and after) twice against the
same "Backend Software Engineer" posting (`required_skills: ["Python",
"SQL", "AWS", "PostgreSQL", "Kubernetes"]`, `min_experience_years: 3.0`,
same as Phase 6) and the same 12 `real_eval_set/` resumes: once with
`SCORING_METHOD=tfidf`, once with `SCORING_METHOD=embedding`, both forced
rescores so every candidate got a fresh score under each method. Phase
6's own comparison script wasn't committed (by design, same as this one),
so its exact job *description* text wasn't available to reuse verbatim —
a new one was written for this run. That doesn't weaken the comparison:
what matters is that both methods in this run scored the identical text,
which they did.

### Full ranked list, both methods, all 12 candidates

```
file             name                     tfidf#  tfidf_final  tfidf_resume  emb#  emb_final  emb_resume  delta
resume_001.pdf   Aaron Whitfield               1         52.3          15.8     1       69.2        58.0      0
resume_002.docx  Priyanka Raghunathan          2         49.4           8.6     2       65.4        48.4      0
resume_012.pdf   Anders Bjornstad              3         41.2           5.4     3       61.3        55.8      0
resume_009.docx  Olumide Adeyemi               4         33.0           2.6     4       41.0        22.5      0
resume_003.pdf   Wei Chen [name bug]           5         30.0          12.4     5       38.6        34.1      0
resume_008.pdf   Hiroshi Tanaka                6         26.3           3.3     6       37.9        32.2      0
resume_004.docx  Maria Fernandez-Lopez         7         25.4           1.0     7       35.3        25.7      0
resume_007.pdf   Nkechi Obi                    8         25.0           0.0    11       26.9         4.7     +3
resume_010.pdf   "Maintained" [name bug]       9         23.0           2.6     8       33.3        28.2     -1
resume_011.docx  Chloe Marchetti              10         22.0           0.0     9       31.7        24.3     -1
resume_006.docx  Samira Haddad                11         17.0           0.7    10       30.8        31.7     -1
resume_005.pdf   Tobias Lindqvist             12         12.8           2.2    12       24.8        27.8      0
```

(`resume_003`'s and `resume_010`'s name-field noise are the same
pre-existing Phase 5 limitations already documented — confirmed again
here to stay contained to the `name` field and not affect either
method's `resume_match`/`final_fit_score`.)

### Observations

**The top 7 are rank-identical between methods.** Both TF-IDF's literal
term overlap and MiniLM's sentence embeddings agree, in the same order,
on who the 7 most-relevant-looking candidates are for this job out of
this pool. That's the headline result: switching ranking method did not
reshuffle the part of the ranking that actually matters for shortlisting.

**The bottom 5 (all genuinely unrelated fields — retail, customer
success, mechanical engineering) reorder under embedding, and the reason
is explainable, not noise.** TF-IDF has a hard floor: zero shared
vocabulary between a resume and the job description resolves to exactly
`0.0` (`resume_007`, `resume_011`: literal `0.0`). Sentence embeddings
have no equivalent hard floor — general "professional resume" text and
general "job posting" text sit at a non-trivial baseline cosine
similarity in embedding space regardless of topical relevance (a known
property of sentence-embedding models, not specific to this codebase).
Concretely: `resume_006`/`resume_010`/`resume_011`'s `resume_match`
jumped from 0.0–2.6 (tfidf) to 24.3–31.7 (embedding), while
`resume_007`'s barely moved (0.0 → 4.7) — that gap alone reordered four
candidates who were all, correctly, near the bottom either way. None of
this changes which candidates are "in contention" (still none of the
bottom 5), but the specific bottom-5 *order* is noisier under embedding
than under TF-IDF, and that noise is structural, not a bug to fix.

**Absolute `final_fit_score` is meaningfully higher under embedding,
which changes `band` classification for the identical resume/job
pairs.** Every one of the 12 candidates reads as `weak_match` under
TF-IDF (the best score, 52.3, doesn't clear the 55.0 `moderate_match`
floor). Under embedding, the top 3 clear it (69.2, 65.4, 61.3 →
`moderate_match`) while the rest stay `weak_match`. This is more than a
cosmetic difference: **`band` is what a recruiter actually acts on, and
the two scoring methods currently disagree about who is worth looking
at, for the identical 12 resumes and the identical job.** PRD F7.5's band
thresholds (55/70/85) were set as fixed values against no particular
scoring method — they weren't calibrated for TF-IDF's score distribution
or for embedding's, and this run shows they don't happen to suit both.
Nobody should read `band` as directly comparable across a
`SCORING_METHOD` switch today. Calibrating band thresholds per method
against a labelled ranking set is now its own `Phases.md` Phase 13 line.

### Semantic skill-match threshold — BLOCKING ISSUE, not merely unvalidated

`SEMANTIC_MATCH_THRESHOLD = 0.5` (`app/ml/skills/skill_gap.py`) is not
just an unmeasured guess sitting harmlessly until Phase 13 — a real-model
sanity check found it **inverted on the cases that matter**, which makes
it actively worse than having no semantic matching at all. Because of
this, **semantic skill matching now refuses to run unconditionally**,
regardless of `SEMANTIC_SKILL_MATCHING`: `scoring_service.py` checks
`skill_gap.THRESHOLD_VALIDATED` (hardcoded `False`) before ever touching
the model, and `config.py` logs a startup `WARNING` if an operator sets
the flag anyway, telling them it currently has no effect. This is not a
"known limitation" of a working feature — the feature is deliberately
inert until a person validates a real threshold and flips
`THRESHOLD_VALIDATED` to `True`.

As an implementation sanity check only (real `all-MiniLM-L6-v2`, not the
mocked model the automated test suite uses — this was never meant as
tuning evidence), a handful of skill-name pairs were scored directly:

```
'PostgreSQL'  vs 'Postgres'                    cosine=0.899  (well above — but these are dictionary aliases of the same canonical skill anyway, so semantic fallback never actually sees this pair)
'Machine Learning' vs 'Deep Learning'          cosine=0.689  above
'Node.js'     vs 'Express.js'                  cosine=0.641  above
'PostgreSQL'  vs 'MySQL'                       cosine=0.547  above
'AWS'         vs 'cloud infrastructure'        cosine=0.492  just below
'Kubernetes'  vs 'container orchestration'     cosine=0.423  below
'Kubernetes'  vs 'Docker Swarm'                cosine=0.347  below
'React'       vs 'Vue.js'                      cosine=0.375  below
'Kubernetes'  vs 'Docker'                      cosine=0.315  below
'Python'      vs 'JavaScript'                  cosine=0.311  below
'CI/CD'       vs 'Jenkins'                     cosine=0.247  below
'SQL'         vs 'watercolor painting'         cosine=0.073  well below
```

The blocking finding is not "the threshold needs tuning" in the abstract
— it's that the errors run in the worse direction:

- **A false negative**: `"Kubernetes"` vs `"container orchestration"`
  (0.423) and `"AWS"` vs `"cloud infrastructure"` (0.492) — both
  reasonable near-paraphrases a recruiter would likely credit — land
  *below* the threshold and would not be promoted to a partial match.
- **A false positive that makes this a blocking issue, not a tuning
  note**: `"PostgreSQL"` vs `"MySQL"` (0.547) lands *above* the
  threshold. These are two different, specific relational database
  products, not the same skill under different names. A candidate
  listing MySQL would get half credit toward a PostgreSQL requirement,
  while a candidate whose skills are genuine paraphrases of what's
  required gets nothing. **A feature that credits the wrong product while
  missing real synonyms is worse than dictionary-only matching**, which
  at least fails predictably (an exact-name miss is always a miss).

This is why the response to this finding was not "tune later, ship now
labelled unvalidated" but "refuse to run until validated." Re-enabling
requires a real threshold validated against `ml/skill_eval`'s labelled
set (Phase 13) and a person flipping `THRESHOLD_VALIDATED`, not a config
change alone.

One real, worth-noting artifact surfaced by this run, not a defect: with
`min_experience_years` set to a modest 3.0, nearly every candidate in the
set — including the ones in completely unrelated fields — cleared the
experience sub-score at 100, since F7.3's ratio is agnostic to whether the
years were spent in a *relevant* field, only whether the candidate has
*some* years. This is the formula working exactly as specified (PRD F7.3
has no relevance qualifier), and resume_match/skill_match are what
actually separate a real match from an unrelated one in this scenario —
worth knowing as a property of a years-only experience signal, not
something Phase 6 was asked to change.

Also visible in this same run, and already fully documented as a Phase 5
limitation (not new, not caused by anything in Phase 6): the two-column
heading-corruption case (`resume_003`, `"Wei Chen EXPERIENCE"` — see
above) and the single-word-name spaCy misfire (`resume_010`, returns
`"Maintained"` instead of `"Ravindran"`) both still show their known
`name` corruption in this ranking's display column. Neither corrupts that
candidate's actual score — `resume_003`'s sub-scores reflect their real
profile (a product designer, correctly scoring 0% skill match against a
backend role) — confirming the pre-existing name-extraction bug stays
contained to the `name` field and does not cascade into scoring.

---

## Phase 8 — Interview question generation, and the grounding filter's real limits

**F8.4's grounding requirement is enforced by a filter, not measured by
one.** Every generated question is checked against a per-candidate
allowlist built from that candidate's own extracted skills, project
entries, and certification entries (never from the job posting) — a
question is kept only if it contains at least one of those strings,
case-insensitively. This is **substring matching, not semantic
understanding**, stated plainly rather than left to be assumed:

- It establishes a **floor**, not a quality bar. It reliably rejects a
  question with zero connection to the candidate's own material (the
  literal "Tell me about yourself" case F8.4 names). It does not
  distinguish a genuinely specific question from a generic one that
  happens to name a real skill — `"Tell me about your experience with
  Python"` passes, because `"python"` is a real anchor for a candidate who
  lists Python, even though the question itself is barely more specific
  than the one F8.4 explicitly bans.
- Found while building this, not merely anticipated: an early version
  tokenized every word out of a candidate's free-text project/certification
  entries as an anchor. A project description like "a real-time inventory
  tracker" leaked the ordinary words "real" and "time" into the anchor set,
  and a fully generic question — *"Tell me about a time you led a
  team"* — passed the filter for no reason other than containing the word
  "time". Fixed by requiring a free-text anchor to look like a proper
  noun/product name (contains a digit, is an all-caps acronym, or has an
  internal capital like "StockWatch") rather than ordinary prose. This
  narrows the failure mode, it does not eliminate it — the same class of
  accidental pass is still possible with any word that both looks
  "specific" and is common enough to land in a generic-sounding sentence.
- Anchors are drawn only from the candidate's own resume-derived data, by
  design (approved design decision, Phase 8 plan review) — a question
  probing a *missing* required skill (e.g. "have you worked with
  Kubernetes?" when Kubernetes isn't on the candidate's list) usually
  fails this filter and gets dropped, since the missing skill isn't in the
  candidate's own vocabulary. This was a deliberate choice, not an
  oversight: broadening anchors to include the job's required skills would
  let a `skill_verification` question survive by naming the gap alone,
  which is generic by construction — exactly what F8.4 exists to prevent.
- **The actual measure of question quality is `ml/llm_eval/`'s human 1–5
  rating (Phases.md Phase 13, PRD F14.4), not this filter.** The filter
  can only ever say a question mentions something real; it cannot judge
  relevance, specificity, or whether the question is actually a good one
  to ask. Do not read "passed grounding" as "high quality."

### Integration verified: one real call against the live API

A real call was made through `POST /candidates/{id}/interview-questions`
against the live provider, not mocked, after the LLM provider was
switched from a non-functional Anthropic key to Groq (Memory.md). It
returned 200 with 5 questions, all passing the grounding filter, for one
fixture candidate: a synthetic resume built around a project called
StockWatch.

- **Model: `openai/gpt-oss-120b`, via Groq** (`OPENAI_BASE_URL` set to
  `https://api.groq.com/openai/v1`). Not Claude, and not the
  `llama-3.3-70b-versatile` originally planned, which Groq had already
  discontinued by the time this call was made (Memory.md decision 47).
  Any future reading of this section's quality findings describes
  `gpt-oss-120b`'s output specifically, not any other model's.
- Captured from the real call's own log line (Rules.md 5.5): 534 input
  tokens, 780 output tokens, 4.11s latency.
- Cost: $0, Groq's free tier. The response's own rate-limit headers
  (`x-ratelimit-limit-requests: 1000`, `x-ratelimit-limit-tokens: 8000`)
  matched the documented free-tier numbers exactly.

This proves the pipeline runs end to end for real: prompt construction,
the actual provider call, strict JSON parsing, the grounding filter, and
persistence. It does not measure question quality.

### F8.4 is NOT verified: open, not a footnote

Phases.md's own Phase 8 acceptance line requires: "Reading two generated
sets side by side, a person can tell which resume produced which — the
questions name real projects, technologies, or claims." That comparison
has never been run. The call above used a single fixture candidate. One
set from one resume cannot show that a reader can tell which resume
produced which, since there is nothing to compare it against. The
integration success above is not evidence for F8.4; it is evidence the
plumbing works, and says nothing about whether the questions are
distinctive or specific enough to tell resumes apart. See Phases.md
Phase 13 for the side-by-side comparison this still requires.

### F8.4 side-by-side run: raw generation is clearly distinguishable, but the production filter rejected it every time

The comparison above was run for real: two genuinely different real
candidates from `real_eval_set/` (`resume_001`, Aaron Whitfield, backend
engineer; `resume_003`, Wei Chen, product designer, also separately
affected by the known two-column name/experience-years corruption,
Phase 5 decision 27, unrelated to what follows) uploaded through the
real extraction pipeline and scored against one real job (Backend
Software Engineer; required skills Python, SQL, AWS, PostgreSQL,
Kubernetes; 3.0 years minimum). Aaron matched 3 of 5 required skills;
Wei Chen matched 0 of 5, a genuine mismatch by profession, same pattern
as the Phase 6/7 real-pipeline runs above.

**The production endpoint returned `503 LLM_INVALID_OUTPUT` on every
real attempt: 5 of 5 for Aaron, 2 of 2 for Wei Chen, 7 of 7 total.** A
further retry round also hit Groq's real per-minute token limit (a live
`429` citing `TPM limit 8000`), directly confirming decision 47's
documented free-tier numbers. Neither candidate ever produced a
question set that reached the database. Both extracted with empty
`projects` and `certifications` — neither resume has a distinct
Projects or Certifications heading; both describe their work only
inside Experience bullets. The grounding filter draws its free-text
anchors solely from `projects`/`certifications`; with both empty, the
only anchors available were bare skill names (8 for Aaron, 5 for Wei
Chen).

A diagnostic call replicating the endpoint's exact prompt-building and
filter logic, but capturing the raw output before the filter discards
anything, showed why. Real results, both candidates, full 7-question
sets:

**Aaron Whitfield** (anchors: distributed systems, go, grpc, kubernetes,
postgresql, python, redis, terraform) — `openai/gpt-oss-120b`, 750 input
tokens, 896 output tokens, 4.09s:

1. REJECT (technical/hard) — "...reduction in p99 checkout latency at
   Corvid Labs?" — real employer and real claimed metric, neither an anchor.
2. REJECT (project/medium) — "...migration of the monolithic billing
   service into four bounded services..." — real named project, not an anchor.
3. REJECT (experience/medium) — "...job-scheduling platform at Meridian
   Systems..." — real employer, not an anchor.
4. PASS (skill_verification/easy) — "...Terraform experience... migrating
   your Kubernetes workloads to AWS..." — contains "terraform"/"kubernetes".
5. REJECT (technical/hard) — "...ingestion layer... at Meridian Systems..."
6. REJECT (behavioral/medium) — "...contract testing... at Corvid Labs..."
7. PASS (technical/easy) — "...Python and Go, and with gRPC..." — contains
   three literal skill anchors.

**Wei Chen** (anchors: communication, css, figma, html, sketch) —
`openai/gpt-oss-120b`, 705 input tokens, 1358 output tokens, 3.25s:

1. REJECT (technical/medium) — "...component library... at Lanterne
   Software..."
2. REJECT (project/easy) — "...onboarding flow at Lanterne Software..."
3. REJECT (experience/medium) — "...mobile companion app at Ashgrove
   Digital..."
4. PASS (skill_verification/medium) — "...HTML/CSS experience... server-side
   rendering with a Python web framework..." — contains "html"/"css", a
   forced cross-discipline question.
5. REJECT (technical/hard) — "...design systems... PostgreSQL schema..." —
   "design systems" is not a listed skill string, so it is not an anchor.
6. REJECT (behavioral/easy) — "...usability sessions... at Ashgrove
   Digital..."
7. REJECT (skill_verification/medium) — "...component library... Kubernetes..."

Aaron: 2 of 7 passed. Wei Chen: 1 of 7 passed.

**Read blind, both sets are unmistakably distinguishable by profession
within the first question** — Aaron's is unambiguously backend and
infrastructure work; Wei Chen's is unambiguously product design work.
F8.4's actual underlying question, whether a reader can tell which
resume produced which, is clearly answered yes by the model's raw
output. **The automated grounding filter is what fails, not question
quality or distinctiveness.** Its rejections are disproportionately the
best, most specific questions in each set, because they name real
employers and projects that live only in the resume's free-text
Experience narrative, a source the filter never reads. It checks only
the structured `skills`/`projects`/`certifications` fields, and the
latter two were empty for both of these ordinary, real,
single-narrative-section resumes.

**This is not an edge case.** Any real resume that describes its work
only inside an Experience section, arguably the majority of ordinary
professional resumes, risks the same outcome: a real `503` to the user
with no questions produced at all, regardless of how good the
underlying model's output actually is. The earlier "Integration
verified" call above did not surface this because it used a synthetic
fixture with a hand-authored, rich `projects` entry ("StockWatch") —
exactly the shape this filter handles well, and exactly the shape an
ordinary real resume without a distinct Projects section will not have.

**This needs a design fix to the grounding filter's anchor coverage,
not just a Phase 13 evaluation run.** Candidate directions, none decided
here: draw additional anchors from named entities in the Experience
section itself; accept a `skill_verification`/behavioral-category
question without requiring a substring match; or reconsider whether a
hard `MIN_QUESTIONS` floor should fail the whole call versus returning
fewer questions with a caveat. See Phases.md Phase 13.

### Grounding-filter fix and post-fix re-run: both real candidates now pass

The anchor-coverage gap above is fixed. `_build_grounding_anchors()`
gained a third source, `_experience_section_anchors()`
(`interview_service.py`), drawing from the candidate's own Experience
section (or the whole resume, only when no EXPERIENCE heading is found
at all — the same fallback `field_extractor.extract_experience_years()`
already uses):

- **Single tokens**, anywhere in the scoped text, via the existing,
  unchanged proper-noun shape rule (digit, all-caps acronym, or internal
  capital) — catches things like `"p99"` and `"API"` named only in a
  bullet. Heading words (`"experience"`, `"education"`, ...) are
  excluded first, via a new `field_extractor.is_heading_word()` built
  from the same heading-phrase list the file already maintains — without
  this, a layout defect that welds a heading onto adjacent text (e.g.
  Wei Chen's `"Wei Chen EXPERIENCE"`, the two-column corruption already
  documented above) would hand the filter a permanent free-pass anchor
  for the word "experience", one of the most common words in any
  interview question.
- **Multi-word proper-noun runs** (2+ consecutive Title-Case words, e.g.
  `"Corvid Labs"`) — a shape no single-token rule can express, since
  neither `"Corvid"` nor `"Labs"` individually has a digit, is all-caps,
  or has an internal capital. Extracted only from a line that also
  contains an employment date range (`field_extractor.find_date_ranges()`,
  the same regex `extract_experience_years()` already uses) — this
  second guard is what excludes the job-title line sitting next to a
  "Company | Dates" line (which has the same 2+-word shape but no date)
  without needing any title-vs-company vocabulary list.

Separately, `_is_grounded()` was rewritten to use the same
word-boundary-safe matcher `skill_matcher.py` already relies on
(`app.utils.text.compile_boundary_pattern`) instead of a plain Python
substring check — a candidate with the skill "Go" was, until this fix,
getting the anchor `"go"`, which matched inside any word containing
that letter pair (e.g. "al**go**rithm"), a false-positive-pass risk that
matters more now that resume-text-derived anchors are doing more of the
filter's work.

The too-few-questions failure mode was also split in two, since "the
model returned garbage" and "the filter rejected too much" are different
failures that a single `LLM_INVALID_OUTPUT` 503 was conflating (this is
exactly what happened on all 7 of the pre-fix attempts above): 1-4
grounded questions now returns 200 with the shorter list and an explicit
`partial: true` flag (`requested`/`generated`/`grounded` are always in
the response body, persisted, so a caller never has to infer partiality
from array length); only a genuine zero-grounded outcome still fails the
call, with a new, distinct code, `INSUFFICIENT_GROUNDED_QUESTIONS`. See
`Rules.md` §5.3 and `docs/API.md`.

**Re-run, for real, against the identical two candidates and job as the
pre-fix run above** (`openai/gpt-oss-120b` via Groq, in-memory SQLite —
`backend/hiring.db` never opened, so untouched by this run):

**Aaron Whitfield** — `requested=8 generated=10 grounded=10 partial=false`.
All 10 generated questions passed, not just enough to clear the floor.
Every one of the 8 returned names a real employer, project, or metric
from the Experience section:

1. (technical/medium) "In the billing service migration at Corvid Labs,
   you mentioned reducing p99 checkout latency by roughly a third
   through query and cache work; can you walk me through a specific
   PostgreSQL query you optimized and the technique you used?"
2. (technical/medium) "What caching strategy did you implement during
   the migration of the monolithic billing service at Corvid Labs to
   achieve latency improvements, and how did you integrate it with
   PostgreSQL?"
3. (project/medium) "How did you design and implement the contract
   testing framework between teams at Corvid Labs, and which tools or
   libraries did you choose for it?"
4. (experience/hard) "Describe the architecture of the internal
   job-scheduling platform you built at Meridian Systems and how it
   supported six different teams simultaneously."
5. (skill_verification/medium) "Although you list PostgreSQL, can you
   provide a concrete example of writing raw SQL (outside an ORM) in a
   production service, perhaps from the ingestion layer you developed at
   Meridian Systems?"
6. (skill_verification/easy) "Have you had any exposure to AWS services
   when deploying Kubernetes workloads, possibly using Terraform, and
   can you describe a specific instance where you applied that
   knowledge?"
7. (behavioral/medium) "During the end-to-end migration of the billing
   service at Corvid Labs, how did you handle on-call incidents after
   the rollout, and what processes did you put in place to ensure
   reliability?"
8. (technical/hard) "The resume lists gRPC as a skill; can you explain
   how you utilized gRPC in the ingestion layer for the partner-facing
   reporting API at Meridian Systems?"

Compare to the pre-fix run above, where the "Corvid Labs"/"Meridian
Systems" questions (1, 2, 4, 5 here) were exactly the ones rejected as
"real employer, not an anchor."

**Wei Chen** — `requested=8 generated=10 grounded=8 partial=false`. Note
`extract_name()` still returns `"Wei Chen EXPERIENCE"` here — the
pre-existing, separately-tracked two-column heading-corruption bug
(Phase 5 decision 27) is untouched by this fix, as expected, and does
not affect the grounding filter: `field_extractor.is_heading_word()`'s
guard against the same welded heading correctly kept "experience" out of
this candidate's anchor set even though `extract_experience_section_text`
falls back to whole-resume scanning here (no clean EXPERIENCE heading to
find).

1. (project/medium) "Can you walk me through the specific challenges you
   faced while rebuilding the onboarding flow at Lanterne Software and
   how you measured its impact on activation rates?"
2. (experience/medium) "What processes did you establish to maintain and
   evolve the component library shared across three product squads at
   Lanterne Software?"
3. (project/hard) "When designing the mobile companion app for Ashgrove
   Digital, which research methods did you employ to ensure the app met
   user needs, and how did those insights shape the final handoff?"
4. (skill_verification/hard) "You list HTML/CSS as a tool in your skill
   set; can you explain how you would structure a RESTful API response
   to support a front-end component you designed in Figma?"
5. (technical/easy) "What criteria did you use to decide when to create
   a new component versus reusing an existing one in the shared library
   at Lanterne Software?"
6. (behavioral/medium) "During your tenure at Ashgrove Digital, can you
   share an example of a design decision that required trade-offs
   between visual fidelity and technical constraints, and how you
   resolved it?"
7. (skill_verification/hard) "Given your experience with Sketch and
   Figma, how would you approach documenting API contracts to ensure
   designers and developers share a common understanding?"
8. (experience/easy) "Your BA in Graphic Communication was completed in
   2018; how have you continued to develop technical competencies (e.g.,
   programming, cloud services) since graduation?"

**Both candidates now succeed comfortably inside the original 5-8
full-success band — neither needed the new 1-4 partial-result path at
all.** 0 of 2 real candidates hit `INSUFFICIENT_GROUNDED_QUESTIONS`,
versus 7 of 7 real attempts hitting `LLM_INVALID_OUTPUT` before this fix.
This is evidence the fix works on the two real resumes it was diagnosed
against; it is not evidence the fix generalizes to every resume shape —
in particular, a company name written on its own line with the date on a
*different* line (a template this fix has no evidence for) would not be
picked up by the multi-word anchor mechanism. The formal `ml/llm_eval/`
human 1-5 rating study (Phase 13) is what actually measures question
quality at scale; this re-run only confirms the production endpoint no
longer fails outright on an ordinary real resume.

---

## Phase 9+ evaluations

Not yet built. This section will gain skill-matching precision/recall/F1
(once semantic matching exists), the LLM question-quality ratings
described above, and attrition model metrics as each phase completes —
see `Phases.md` Phase 13.
