"""Stable supervised dataset schema and explicit column roles."""

from __future__ import annotations


SCHEMA_VERSION = "dota-draft-supervised-v1"

IDENTIFIER_COLUMNS = (
    "sample_id",
    "game_key",
    "source_game_id",
    "game_index",
)
GROUP_IDENTIFIER_COLUMNS = ("source_match_id",)
TIME_COLUMNS = ("match_start_utc",)
CONTEXT_FEATURE_COLUMNS = (
    "patch",
    "liquipedia_tier",
    "tournament",
    "series",
    "radiant_team_key",
    "dire_team_key",
)
RADIANT_PICK_COLUMNS = tuple(
    f"radiant_pick_slot_{slot}"
    for slot in range(1, 6)
)
DIRE_PICK_COLUMNS = tuple(
    f"dire_pick_slot_{slot}"
    for slot in range(1, 6)
)
RADIANT_BAN_COLUMNS = tuple(
    f"radiant_ban_slot_{slot}"
    for slot in range(1, 8)
)
DIRE_BAN_COLUMNS = tuple(
    f"dire_ban_slot_{slot}"
    for slot in range(1, 8)
)
DRAFT_FEATURE_COLUMNS = (
    *RADIANT_PICK_COLUMNS,
    *DIRE_PICK_COLUMNS,
    *RADIANT_BAN_COLUMNS,
    *DIRE_BAN_COLUMNS,
)
TARGET_COLUMNS = ("radiant_win",)

TRAINING_COLUMNS = (
    *IDENTIFIER_COLUMNS,
    *GROUP_IDENTIFIER_COLUMNS,
    *TIME_COLUMNS,
    *CONTEXT_FEATURE_COLUMNS,
    *DRAFT_FEATURE_COLUMNS,
    *TARGET_COLUMNS,
)

FORBIDDEN_COLUMNS = frozenset(
    {
        "duration_seconds",
        "winner_team_slot",
        "score",
        "walkover",
        "result_type",
        "status",
        "first_pick",
        "first_pick_team_slot",
        "global_draft_order",
        "global_draft_sequence",
    }
)


def schema_payload() -> dict[str, object]:
    """Return the machine-readable canonical schema contract."""
    roles = {
        **{column: "identifier" for column in IDENTIFIER_COLUMNS},
        **{
            column: "group_identifier"
            for column in GROUP_IDENTIFIER_COLUMNS
        },
        **{column: "time" for column in TIME_COLUMNS},
        **{
            column: "context_feature"
            for column in CONTEXT_FEATURE_COLUMNS
        },
        **{column: "draft_feature" for column in DRAFT_FEATURE_COLUMNS},
        **{column: "target" for column in TARGET_COLUMNS},
    }
    nullable = {
        column: column
        in {
            "source_game_id",
            "match_start_utc",
            "patch",
            "liquipedia_tier",
            "tournament",
            "series",
            "radiant_team_key",
            "dire_team_key",
        }
        for column in TRAINING_COLUMNS
    }
    logical_types = {
        column: (
            "boolean"
            if column == "radiant_win"
            else (
                "integer"
                if column == "game_index"
                else (
                    "utc_timestamp"
                    if column == "match_start_utc"
                    else "string"
                )
            )
        )
        for column in TRAINING_COLUMNS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "grain": "one row per eligible completed professional Dota 2 game",
        "prediction_point": "completed draft before gameplay",
        "columns": list(TRAINING_COLUMNS),
        "roles": roles,
        "nullable": nullable,
        "logical_types": logical_types,
        "feature_columns": [
            *CONTEXT_FEATURE_COLUMNS,
            *DRAFT_FEATURE_COLUMNS,
        ],
        "draft_feature_columns": list(DRAFT_FEATURE_COLUMNS),
        "target_column": "radiant_win",
        "forbidden_columns": sorted(FORBIDDEN_COLUMNS),
        "unsupported_semantics": {
            "first_pick": "Unavailable; never infer.",
            "global_draft_order": "Unavailable; never reconstruct.",
            "slot_interpretation": "Per-team slot ordering only.",
        },
    }
