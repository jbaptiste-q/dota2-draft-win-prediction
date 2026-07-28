"""Approved LiquipediaDB request contract for historical Dota 2 matches."""

from __future__ import annotations


ACQUISITION_VERSION = "liquipedia-history-v1"
API_URL = "https://api.liquipedia.net/api/v3/match"
WIKI = "dota2"
USER_AGENT = "Dota2AIPortfolioBackfill/1.0"

MATCH_FIELD_PROJECTION = (
    "pageid",
    "pagename",
    "namespace",
    "objectname",
    "match2id",
    "status",
    "winner",
    "walkover",
    "resulttype",
    "finished",
    "patch",
    "date",
    "dateexact",
    "bestof",
    "tournament",
    "parent",
    "series",
    "liquipediatier",
    "extradata",
    "match2games",
    "match2opponents",
)

DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_REQUESTS = 4
DEFAULT_HOURLY_REQUEST_LIMIT = 54
DEFAULT_REQUEST_INTERVAL_SECONDS = 67.0
