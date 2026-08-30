# Setup

**Placeholder.** The full "local setup from scratch" guide is a Phase 16
deliverable (`Phases.md`) and has not been written yet. This file
currently carries only one step, added during Phase 10 because it
affects a fresh clone immediately, not because Phase 16 has started.

## Attrition model artifacts are not in the repository

`ml/attrition/artifacts/*.joblib` is gitignored by design (`Phases.md`
Phase 0). A fresh clone therefore has no trained attrition model on disk.
Three scripts must all be run before server startup can serve attrition
predictions — until then, Phase 11's attrition endpoints return
`503 ATTRITION_MODEL_MISSING` at request time (every other endpoint is
unaffected; startup itself does not fail):

```bash
python ml/attrition/03_train.py
python ml/attrition/09_finalize_calibrated_model.py
python ml/attrition/12_finalize_risk_tier.py
```

This requires `data/raw/WA_Fn-UseC_-HR-Employee-Attrition.csv` to be
present first — see `data/README.md` for how to obtain it.

`03_train.py` creates the base artifacts: `model.joblib` (the fitted,
uncalibrated Logistic Regression + SMOTE pipeline), `preprocessor.joblib`,
`feature_names.json`, `metrics.json`, and `decision_threshold.json`'s
top-level `0.550` evaluation-script cutoff. `python ml/attrition/04_evaluate.py`
is optional at setup time — it only re-confirms `03_train.py`'s sealed-test
numbers into `metrics.json` and is not required for serving.

`09_finalize_calibrated_model.py` persists the already-validated,
sigmoid-calibrated serving model as `calibrated_model.joblib` and adds
`decision_threshold.json`'s `"calibrated"` section, which records the
calibrated serving threshold **0.2005** — the number the API actually
applies to `flagged`. It re-derives Phase 10's 4-seed calibration
recommendation and asserts the result matches what was already validated
before writing anything (see `Memory.md` decision 71); it does not retrain,
reselect a model, or choose a new threshold.

`12_finalize_risk_tier.py` persists the owner-approved, frozen empirical
risk-tier cutoffs as `decision_threshold.json`'s `"risk_tier"` section —
`0.3671` (High) / `0.2270` (Medium), derived from the four-seed calibrated
out-of-fold probability distribution (Memory.md, 2026-08-30 owner
decision, resolving PRD F9.7). It re-derives those same percentiles and
asserts the result matches the recorded, approved values before writing
anything; it does not choose a new scheme or recompute anything at
request time.

**A fresh setup is incomplete without both finalization steps.** Running
only `03_train.py` produces `model.joblib` but not `calibrated_model.joblib`,
`decision_threshold.json`'s `"calibrated"` section, or its `"risk_tier"`
section — `predictor.load_artifacts()` treats any of the three being
missing as `ATTRITION_MODEL_MISSING`, by design (Phases.md Phase 11: a
missing or inconsistent artifact set degrades only the attrition routes,
loudly, rather than serving something partially built). All three
commands above must be run, in order.
