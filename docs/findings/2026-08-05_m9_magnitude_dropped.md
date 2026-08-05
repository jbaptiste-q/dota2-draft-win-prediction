# Finding: magnitude dropped from Milestone 9

Date: 2026-08-05

## What happened

In the Milestone 9 Phase 2 Step 2A model-selection experiment (120
hand-annotated changes, three candidate models), magnitude accuracy
against the human annotation was far below the majority-class baseline
for every model:

| Model | Magnitude accuracy | Magnitude κ | Baseline (always "moderate") |
| --- | --- | --- | --- |
| claude-haiku-4-5-20251001 | 0.250 (30/120) | 0.018 | 0.725 |
| claude-sonnet-5 | 0.225 (27/120) | −0.010 | 0.725 |
| claude-fable-5 | 0.292 (35/120) | 0.025 | 0.725 |

All three models score well under half the trivial baseline, and κ is
statistically indistinguishable from zero for all three -- essentially
chance-level agreement with the human annotation. By contrast, direction
accuracy on the same 120 items was 62-70% against a 36% baseline, with
κ in the 0.48-0.58 range: a real, measurable signal.

## Attribution

This is attributed to an under-specified annotation protocol, not to the
models. The annotation guide (`annotation_guide.md`) gave a definition
for magnitude (`minor | moderate | major | unclear`) but no anchoring
examples distinguishing them -- no worked case showing what makes a
change "minor" versus "major." Both the human annotator and each model
independently had to invent their own implicit scale, and those scales
never aligned with each other. This reads as a protocol failure (no
shared reference point was given to align against), not a model
capability failure -- direction, which had concrete behavioral anchoring
("cooldown/mana/cast time going up are nerfs," "structural changes are
rework not buff/nerf"), performed far better across the same items and
same models.

## Disposition

Magnitude labeling is dropped from Milestone 9. The protocol is not
being fixed and re-run: per-project judgment, the finding itself (that
an unanchored magnitude scale produces unusable inter-rater agreement)
is worth more than the label would have been. Re-running would cost
another full annotation pass for a dimension Phase 4 does not strictly
need.

**Phase 4 uses direction only.** `change_type` and `confidence` remain
in the label schema (they were not evaluated here and are not implicated
by this finding); `magnitude` is not used downstream.
