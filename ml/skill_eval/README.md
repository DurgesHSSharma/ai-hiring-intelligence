# Skill-matching evaluation — human-labelling package (Phase 13, F14.2 and F4.4)

**Status: two distinct labelling sheets prepared, both unlabelled. No metric has been computed, no threshold has been chosen, `THRESHOLD_VALIDATED` has not been changed. No code has been changed.**

This directory holds **two separate labelling tasks** that must not be
conflated — they answer different questions and feed different parts of
Phase 13:

| Sheet | Answers | Feeds |
|---|---|---|
| `skill_list_labelling_sheet.csv` | "What skills does this resume actually support?" | F14.2 — dictionary skill-extraction precision/recall/F1 |
| `semantic_threshold_pairs_labelling_sheet.csv` | "Should this specific pair of terms count as a match?" | F4.4 / `SEMANTIC_MATCH_THRESHOLD` validation, gated by `THRESHOLD_VALIDATED` in `app/ml/skills/skill_gap.py` |

## 1. Skill-list labelling (`skill_list_labelling_sheet.csv`)

Per Phases.md Phase 13, needs ≥30 hand-labelled resumes. This sheet uses
the existing **`backend/tests/fixtures/regression_eval_set/`** corpus —
already exactly 30 real-format resumes, already an established
evaluation fixture (used for Phase 5's field-extraction regression
testing), just missing a `skills` field — rather than building a new
corpus from scratch.

**30 rows, one per resume.** Columns: `resume_id`, `source_set`,
`source_file` (path to the actual fixture file), `candidate_id_live_system`
(the real database id this resume was assigned when uploaded through the
production pipeline this session, for cross-reference against
`ml/ranking_eval/source_data_snapshot.json` if useful — not needed to do
the labelling itself), `gold_skills` (**blank**), `human_notes` (**blank**).

### Labeling protocol

**Read independently first — do not use `data/skills.json` as a
checklist.** Open the source file (`source_file` — read the actual
document, not a summary) and read it the way a careful, independent
human reader would, *before* consulting `data/skills.json` or any
extractor output at all. This order is mandatory, not a stylistic
preference: starting from the dictionary's vocabulary and checking
which entries "fit" the resume would silently anchor the gold labels
to the system's own vocabulary, artificially inflating precision/recall
— the exact failure mode this evaluation exists to catch, not commit.

Credit a skill only when, on that independent read:

- the resume **explicitly names** the skill, or
- the resume **describes a direct use or application** of it.

Do **not** credit a skill merely because it is *implied* by:

- job title
- seniority
- job function
- general responsibilities

For example: "Led a team of four" does **not** by itself become
`Leadership` — leading four people doesn't explicitly name or
demonstrate the skill of leadership as such. But "Supply chain
management" written explicitly on the resume **does** count as a
domain skill — it's named outright, not inferred from a title or duty.

**Only after** the independent reading pass is complete, map each
clearly-matching credited skill to its canonical name in
`data/skills.json`:

- If a resume skill clearly corresponds to a canonical entry (by name
  or a listed alias), record the **canonical name**.
- If no canonical entry clearly fits, record the resume's **own
  wording** as free text instead.
- **Never force an ambiguous mapping** — when it's unclear whether a
  canonical entry is really the same skill the resume names, keep the
  free-text wording rather than guessing.

### Format

- `gold_skills` entries are **semicolon-separated**.
- Skill comparison against extractor output will eventually be
  **case-insensitive** — matching the case-insensitive matching
  `skill_matcher.py` (`compile_boundary_pattern`, `re.IGNORECASE`) and
  `skill_gap.py` already use in production; this labelling convention
  follows an existing rule rather than introducing a new one.
- Every free-text fallback (a credited skill with no canonical
  `skills.json` entry) must also be noted in `human_notes`, so
  dictionary-coverage gaps can be measured later, separately from
  extractor misses.

### Provenance requirement

The gold labels must be an **independently judged** gold standard, not
a byproduct of inspecting the system under test. Whoever performs the
independent reading-and-judging pass above must **not** have inspected
`skill_matcher.py`, `skill_gap.py`, or `data/skills.json` as part of
*making that judgment* — inspecting those first and then labeling would
reproduce the exact anchoring bias this protocol exists to prevent,
even if no extractor output is literally shown. Purely **mechanical
transcription/formatting** of an already-made independent judgment
(e.g. copying a finished list into the CSV, or applying the
canonical-mapping step above to skills already credited) is fine — but
the decision of *which* skills to credit must never be made with the
extractor or the vocabulary file already in view.

**Deliberately not shown, for the same reason:** this sheet does not
include what the system's own dictionary matcher currently extracts for
each resume. Showing that would anchor the human labeler toward the
model's own output, defeating the purpose of an independent gold
standard — precision/recall/F1 computed later against a biased gold set
would be inflated and meaningless. The comparison against the system's
actual output happens in the evaluation step, after labelling, not
before.

### Metrics to compute later

Evaluation should measure **extraction + normalization** against the
canonical vocabulary, not extraction alone — a correct skill returned
in the wrong form is still a miss for a system that's supposed to
return canonical names. It should also separately distinguish two
different kinds of miss, because they call for different fixes:

a. **Known-vocabulary misses** — the skill has a canonical
   `skills.json` entry, but the extractor failed to find it in the
   resume text (a matching bug or a missing alias).
b. **Vocabulary-coverage misses** — the human credited a real skill for
   which `data/skills.json` has no suitable entry at all (a dictionary
   coverage gap, not a matching failure).

Conflating these two would misdiagnose a coverage gap as a matching bug
or vice versa; the `human_notes` free-text-fallback flag above is what
makes this distinction possible later.

## 2. Semantic threshold pairs (`semantic_threshold_pairs_labelling_sheet.csv`)

**This is a 20-pair human validation set, and it is intentionally
separate from the 30-resume gold-skill evaluation above** — a
separate task, per explicit instruction, not a byproduct of the
skill-list labelling. It exists to validate (or invalidate)
`SEMANTIC_MATCH_THRESHOLD` (`app/ml/skills/skill_gap.py`, currently
`0.5`) before `THRESHOLD_VALIDATED` can ever be flipped to `True` and
F4.4 (semantic skill-fallback matching) can be enabled.

**Why this exists as its own thing:** a resume's overall gold skill list
(task 1 above) tells you *what a candidate has*. It does not by itself
tell you whether "AWS" on a job posting should credit a candidate who
wrote "cloud infrastructure" instead — that is a judgment about a
specific *pair of terms*, independent of any one resume. Phase 7's own
real-model sanity check (recorded in `app/ml/skills/skill_gap.py`'s code
comments and `Memory.md`) found the guessed 0.5 threshold **inverted**
on exactly this kind of case: `"PostgreSQL"`/`"MySQL"` (two different
products) scored 0.547 (above threshold — would incorrectly count as a
match), while `"AWS"`/`"cloud infrastructure"` (a genuine paraphrase)
scored 0.492 (below threshold — would incorrectly be rejected).

**20 rows.** Columns: `pair_id`, `term_a`, `term_b`, `category`,
`context_source`, `human_match_label` (**blank**), `human_notes` (**blank**).

Every `term_a` is a real canonical skill name from
`backend/app/data/skills.json` (F4.1's 423-entry skill dictionary).
Every `term_b` is either another real canonical skill name from the same
file, or a plausible free-text phrasing a candidate might actually write
that is **not** itself a listed alias of `term_a` (verified against the
file) — meaning it is exactly the kind of case dictionary/alias matching
cannot resolve, which is the entire reason F4.4's semantic fallback
exists. `context_source` cites exactly where each term came from.

The two pairs Phases.md's own instruction requires at minimum are
included: `AWS`/`cloud infrastructure` (row P001) and
`PostgreSQL`/`MySQL` (row P002) — the exact pair from the Phase 7
finding above.

`category` labels the **type** of linguistic relationship each pair is
testing — it is descriptive metadata, not a suggested answer:

- `synonym_paraphrase` — a genuine paraphrase that arguably should match
- `related_distinct` — related but genuinely different technologies
- `near_miss` — debatable, doesn't cleanly fall into either bucket above
- `abbreviation` — an industry-standard acronym/shorthand
- `hierarchical` — a general category term vs. one specific instance of it

Judge each row on its own merits — the category label is there to make
sure the set has a defensible spread across relationship types, not to
hint at how you should rate any individual pair.

### Instructions for the labeler

For each pair, decide: **if a candidate's resume said `term_b`, and a
job required `term_a`, should the system credit that as a match (even a
partial one)?** Record your judgment in `human_match_label` — a
free-text or short-code judgment is fine (e.g. "yes"/"no"/"partial", or
your own scale), whatever is clearest to you; it is not being
constrained to a specific coding scheme here, since it does not need to
feed a specific formula on its own — it exists to check whether a single
numeric similarity threshold can plausibly separate the "should match"
rows from the "should not match" rows at all.

### What was NOT done

No threshold was chosen. No claim of "validated" was made anywhere.
`THRESHOLD_VALIDATED` in `app/ml/skills/skill_gap.py` is still `False`,
and `SEMANTIC_SKILL_MATCHING` was not touched. Per Phases.md Phase 13,
validating a real threshold against this labelled set — once it's
filled in — and then flipping `THRESHOLD_VALIDATED` is separate,
later work, and needs the project owner's own review of the evidence
before it happens, not an automatic flip once labels exist.

### Provisional evidence — a 20-pair set is a starting point, not a full validation

**Any threshold evidence produced from this set once it is labelled
should be treated as provisional, because 20 pairs is a small
validation set.** Twenty rows can indicate whether a single numeric
similarity threshold plausibly separates "should match" from "should
not match" cases at all (which is what the Phase 7 finding already put
in doubt — see above), and can rule out a threshold that is clearly
wrong. It is not large enough on its own to precisely tune a production
threshold with confidence, characterize behavior across the full range
of technical-domain vocabulary the real skill dictionary covers (423
entries across 4 skill types), or rule out edge cases this specific
20-row selection didn't happen to cover.

**If the evidence from labelling this set turns out ambiguous or
insufficient** — e.g. the "should match" and "should not match" rows
don't separate cleanly at any single threshold, or the labeler's own
judgments are inconsistent on similar pairs — **a future expansion of
this set (more pairs, more coverage of skill types/relationship kinds)
may be required** before `THRESHOLD_VALIDATED` can be responsibly
flipped. This sheet is not being presented as sufficient by
construction; whether 20 pairs turns out to be enough is itself part of
what the labelling and subsequent analysis need to determine.

### A note on scope

If the repository had not contained enough real, defensible material
for this sheet, the right move would have been to report that shortfall
rather than invent skill-term pairs. That wasn't necessary here —
`backend/app/data/skills.json`'s 423 real canonical entries (with
aliases) provided enough material to build a 20-row set spanning all
five requested relationship types without inventing anything.
