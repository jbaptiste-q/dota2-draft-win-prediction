# Project Conventions

This is a completed Dota 2 draft-modeling project. Milestones 1 through
4B.3 are done, validated, and documented under docs/milestones/.

## Never modify

- src/liquipedia_backfill/ (acquisition, cache, SQLite ledger, checkpoints)
- src/liquipedia_pipeline/ (parsing, normalization, eligibility)
- src/draft_training_dataset/ (supervised schema and builder)
- Any code path that can issue an authenticated HTTP request
- Any existing milestone document under docs/

If a task seems to require changing these, stop and ask.

## Locked test policy

The interval [2026-01-01T00:00:00Z, 2026-04-01T00:00:00Z) is sealed.
Zero transforms, zero predictions, zero target reads. The interval
[2025-10-01T00:00:00Z, 2026-01-01T00:00:00Z) is reserved for
calibration and must not be used for model selection.

Violating either boundary invalidates the project. Treat these as hard
constraints, not preferences.

## Testing

Baseline before any change:

    env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 .venv/bin/python -m pytest -q

Expected: 424 passed. Run this after every logical step. If the count
drops, stop and report before continuing.

Also available:

    .venv/bin/python -m compileall -q src scripts tests
    .venv/bin/python scripts/check_repository_hygiene.py

## Dependencies

Current direct dependencies are duckdb, pandas, pytest, joblib. Do not
add PyTorch, TensorFlow, JAX, or any deep-learning framework. Implement
gradient-based fitting with numpy and hand-derived gradients.

## Documentation

New milestone documents go in docs/milestones/ and must stay under 150
lines. Include only: frozen inputs, method, results tables, gate
outcome, artifact list, validation summary. Do not produce a full
Definition-of-Done artifact.

## Git workflow

- Work on a feature branch, never commit directly to main
- One commit per logical step, conventional commit format
- Run the test suite and check_repository_hygiene.py before every commit
- Show `git diff --cached --stat` and wait for my confirmation before pushing
- Never commit anything under models/, data/raw/, data/processed/,
  data/training/, or .secrets/

## Model selection per phase

Model switching is manual via /model. It does not happen automatically.
At the start of each phase, remind me which model is recommended and
wait for my confirmation before proceeding.

| Phase | Recommended model | Reason |
| --- | --- | --- |
| 1 - Synthetic validation | Fable 5 | Hand-derived gradients, finite-difference checks, degenerate-case proofs |
| 2 - Configuration contract | Sonnet 5 | Structural work mirroring an existing config |
| 3 - Experiment | Fable 5 | Leakage boundaries, fold-wise fitting, numerical stability |
| 4 - Interpretability artifacts | Sonnet 5 | Deterministic exports |
| 5 - Documentation and tests | Sonnet 5 | Writing and routine test coverage |

If a phase runs into a problem the current model cannot resolve after
two attempts, stop and suggest escalating rather than continuing.
