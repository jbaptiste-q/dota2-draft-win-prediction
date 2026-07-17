# Data and leakage guide

## What one row means

Each row represents one professional Dota 2 match. Radiant and Dire each have five hero picks. The target, `radiant_win`, is `true` when `winner_id` equals `radiant_team_id` in the raw data.

## The 25 columns in the processed sample

| Column(s) | Version-one role | Junior-friendly explanation |
|---|---|---|
| `match_id` | Tracking only | Identifies a match and helps detect duplicates. Do not give arbitrary IDs to the model. |
| `match_start_date_time` | Split only | Use this to split old matches into training data and newer matches into validation/test data. |
| `game_version_id` | Model feature | Patch ID known before play; hero balance changes between patches. |
| `game_version` | Display only | Human-readable patch name. It duplicates `game_version_id`. |
| `radiant_player_1_hero_id` through `radiant_player_5_hero_id` | Model features | The five Radiant hero picks. |
| `dire_player_1_hero_id` through `dire_player_5_hero_id` | Model features | The five Dire hero picks. |
| The ten matching columns ending in `_hero` | Display only | Hero names make the CSV understandable but duplicate the numeric hero IDs. |
| `radiant_win` | Target | The value the future model will predict. Never include it among input features. |

The exact ordered column list is also stored in `data/processed/sample_metadata.json`.

## What data leakage means

Data leakage happens when a model receives information that would not exist at the moment the prediction is supposed to be made. Leakage can produce excellent test scores while creating a useless real-world model.

Our prediction moment is **immediately after the draft and before gameplay begins**. This timing rule makes feature decisions much clearer.

## Columns excluded because they leak the answer

- `winner_id` directly states the winning team. It is used once to create `radiant_win`, then removed.
- `match_duration_seconds`, `first_blood_time_seconds`, `radiant_kills`, and `dire_kills` are generated during or after play.
- Every player column ending in `_kills`, `_deaths`, `_assists`, or `_networth` describes what happened in the match.
- Player `_position`, `_lane`, and `_role` fields are excluded as a leakage risk because the dataset may infer them from match activity. We should not use them until their creation timing is verified.

## Columns excluded only to keep version one simple

Not every excluded column is leakage. This distinction matters.

- League, series, region, and tier metadata may be known before a match, but are outside a minimal draft-only baseline.
- Team and player identities may also be known beforehand, but they introduce high-cardinality reputation effects and make evaluation more complicated.
- Hero names duplicate hero IDs, so names are kept for humans but not used as additional model inputs.
- `match_id` is an identifier, not a meaningful game feature.

These fields could be studied in later versions after the draft-only baseline is trustworthy.

## Why use a chronological split later

Randomly mixing old and new matches can let the same teams, players, tournament series, and patch environment appear on both sides of the evaluation. A chronological split better imitates the real task: learning from the past and predicting newer matches.

No split or model has been created yet. For now, `match_start_date_time` is retained so that choice can be made transparently during exploratory analysis.

## Full raw-column inventory

`column_inventory.csv` lists all 130 source columns. Its `v1_decision` values mean:

- `use_feature`: planned model input.
- `target_derivation_only`: needed to construct or verify the label, then removed.
- `split_only`: used to create honest time-based data splits.
- `tracking_only`: useful for data quality and traceability.
- `display_only`: retained for human readability but not used by the model.
- `exclude_leakage`: definitely contains information from the match outcome or gameplay.
- `exclude_leakage_risk`: timing is uncertain, so exclusion is the safe choice.
- `exclude_scope`: potentially valid later, but intentionally omitted from the simplest baseline.
