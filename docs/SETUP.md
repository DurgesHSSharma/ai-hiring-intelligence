# Setup

**Placeholder.** The full "local setup from scratch" guide is a Phase 16
deliverable (`Phases.md`) and has not been written yet. This file
currently carries only one step, added during Phase 10 because it
affects a fresh clone immediately, not because Phase 16 has started.

## Attrition model artifacts are not in the repository

`ml/attrition/artifacts/*.joblib` is gitignored by design (`Phases.md`
Phase 0). A fresh clone therefore has no trained attrition model on disk.
`ml/attrition/03_train.py` must be run once before server startup can
serve attrition predictions — until then, Phase 11's attrition endpoints
return `503 ATTRITION_MODEL_MISSING` at request time (every other
endpoint is unaffected; startup itself does not fail).

To produce the model artifacts locally:

```bash
python ml/attrition/03_train.py
python ml/attrition/04_evaluate.py
```

This requires `data/raw/WA_Fn-UseC_-HR-Employee-Attrition.csv` to be
present first — see `data/README.md` for how to obtain it.
