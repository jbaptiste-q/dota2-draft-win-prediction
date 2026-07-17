# Data and leakage guide

## Prediction context

Each row represents one professional Dota 2 match. Radiant and Dire each have five hero picks. The target, `radiant_win`, is true when Radiant wins.

The prediction point is immediately after the draft and before gameplay begins. Every model feature must be available at that moment.

## Processed columns

| Column(s) | Use | Rationale |
| --- | --- | --- |
| `match_id` | Tracking | Identifies matches and supports duplicate checks. |
| `match_start_date_time` | Data split | Orders matches for chronological evaluation. |
| `game_version_id` | Feature | Represents the patch known before the match starts. |
| `game_version` | Reference | Provides a readable patch name without duplicating the numeric feature. |
| `radiant_player_1_hero_id` through `radiant_player_5_hero_id` | Features | Identify the five Radiant hero picks. |
| `dire_player_1_hero_id` through `dire_player_5_hero_id` | Features | Identify the five Dire hero picks. |
| The ten matching columns ending in `_hero` | Reference | Provide readable hero names while the model uses hero IDs. |
| `radiant_win` | Target | Records whether Radiant won and never enters the feature matrix. |

The ordered column list is stored in `data/processed/sample_metadata.json`.

## Leakage policy

Data leakage occurs when a model receives information that would not be available at prediction time. It can produce strong evaluation scores without producing a useful model.

The following fields are excluded:

- `winner_id`, which directly identifies the winner
- match duration, first-blood time, team kills, and other values known only during or after gameplay
- player kills, deaths, assists, and net worth
- player position, lane, and role fields whose timing is uncertain
- the target and all fields derived from the final result

## Scope exclusions

Some fields may be known before a match but are outside the draft-focused baseline:

- league, series, region, and tournament tier
- team and player identities
- hero names that duplicate hero IDs
- match IDs and other tracking fields

These fields could support later experiments, but they would introduce reputation effects, higher-cardinality features, or redundant information.

## Chronological evaluation

The split follows match time:

| Split | Matches | Period |
| --- | ---: | --- |
| Train | 21,004 | Through 2022-11-11 |
| Validation | 4,496 | 2022-11-12 through 2023-11-19 |
| Test | 4,500 | After 2023-11-19 through 2024-10-15 |

This setup better reflects the real task of learning from past drafts and predicting matches from newer patches and competitive environments.

## Raw-column inventory

`column_inventory.csv` documents all 130 source columns. The `v1_decision` field uses these labels:

- `use_feature`: model input
- `target_derivation_only`: used to construct or verify the target
- `split_only`: used for chronological splitting
- `tracking_only`: retained for quality checks and traceability
- `display_only`: retained for readability
- `exclude_leakage`: unavailable at prediction time
- `exclude_leakage_risk`: excluded because availability is uncertain
- `exclude_scope`: potentially useful but outside the current project scope
