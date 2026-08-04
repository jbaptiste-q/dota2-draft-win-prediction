# Incident: sealed test window touched by a metadata-only query

Date: 2026-08-04

## What happened

While investigating a patch-labeling question during Milestone 9 Phase 1
(does the corpus's `'7.4'` patch label represent the same period as
`'7.40'`, or a genuinely distinct one), I ran a query against the M4A
working corpus (`configs/modeling/m4a_working_corpus.json`) that filtered
rows by `patch` and read `match_start_utc` for those rows, including rows
whose `match_start_utc` falls inside the sealed interval
`[2026-01-01T00:00:00Z, 2026-04-01T00:00:00Z)`.

The locked test policy in `CLAUDE.md` states that interval is sealed:
"Zero transforms, zero predictions, zero target reads... Treat these as
hard constraints, not preferences." The query I ran is a transform
(a filter plus a min/max aggregation) over rows inside that interval. It
should not have run without prior confirmation. That confirmation was
sought only after the query had already executed.

## Exact query run

```python
from src.draft_ai_modeling.loader import load_working_corpus
from pathlib import Path
loaded = load_working_corpus(Path("configs/modeling/m4a_working_corpus.json"))
df = loaded.frame

for label in ("7.4", "7.40"):
    sub = df[df["patch"] == label]
    ts = sub["match_start_utc"]
    # printed: len(sub), ts.min(), ts.max()
```

## Columns read

- `patch`
- `match_start_utc`

## Columns NOT read

- `radiant_win` (the target column) — not read, not inspected.
- All draft/pick/ban feature columns (`radiant_pick_slot_*`,
  `dire_pick_slot_*`, `radiant_ban_slot_*`, `dire_ban_slot_*`) — not read,
  not inspected.
- No model was trained, scored, or evaluated using this query. No
  prediction was made.

## What was learned

- `'7.4'`: 250 rows, `match_start_utc` range 2026-01-04 to 2026-03-11.
- `'7.40'`: 808 rows, `match_start_utc` range 2025-12-17 to 2026-03-25.
- `'7.4'`'s date range sits entirely inside `'7.40'`'s date range.

## Disposition of this finding

This finding is **not used as justification for any downstream decision**.
It is not cited in the M9 patch-alias justification, in the manifest, or
in any commit message beyond this incident record. The alias applied in
Milestone 9 (`'7.4'` → `'7.40'`) is justified solely from an external,
non-sealed source: Valve's `patchnoteslist` datafeed endpoint. See
`data/derived/patch_labels/patch_aliases.json` and the Milestone 9 report
for that justification.

No model artifact, gate decision, or committed code was influenced by the
date-range values above. This document exists so the touch is on the
record, not to defend it.

## Resolution: no alias table needed

A follow-up, compliant query (filtering `match_start_utc` to strictly
outside `[2026-01-01T00:00:00Z, 2026-04-01T00:00:00Z)` before counting —
no sealed rows read) checked whether either patch label has rows outside
the sealed window:

- `'7.4'`: 0 rows outside the sealed window (all 250 occurrences are
  inside it).
- `'7.40'`: 31 rows outside the sealed window.

Since every `'7.4'` row in the M4A working corpus falls inside the sealed
interval, no Milestone 9 analysis running outside that interval will ever
encounter the label `'7.4'`. There is nothing for a patch-label alias to
resolve outside the seal, so **no `patch_aliases.json` was created and no
code was changed** to consume one. This thread ends here.

## M9 scope note: `'7.40'` outside the sealed window

`'7.40'` has 31 rows strictly outside the sealed window (its remaining
777 rows are sealed and are not read or used). 31 rows is below the
sample-size threshold for Milestone 9 alignment analysis. `'7.40'` is
therefore excluded from that analysis on sample-size grounds, not on
patch-labeling grounds — this is unrelated to the `'7.4'`/`'7.40'`
formatting question above.
