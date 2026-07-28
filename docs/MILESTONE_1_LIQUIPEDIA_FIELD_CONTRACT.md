# Liquipedia API Field-Level Data Contract

## Milestone 1 Contract Audit

**Status:** Draft payload paths sample-validated; historical coverage and player-performance verification pending
**Contract version:** 0.2
**Documentation inspected:** July 27, 2026
**API version:** LiquipediaDB API v3 / OpenAPI 3.0.0
**Wiki identifier:** `dota2`
**Data-source policy:** Official Liquipedia APIs and documentation only. No scraping.

This document defines what the authenticated LiquipediaDB v3 documentation contractually exposes, how those fields map to the product, and which requirements remain unverified because they are stored inside untyped JSON containers.

It complements [Milestone 1: Product, Data, and System Architecture](./MILESTONE_1_PRODUCT_DATA_ARCHITECTURE.md).

## 1. Executive Verdict

The authenticated API documentation is sufficient for:

- Tournament and tournament-series metadata.
- Series-level match scheduling and results.
- Team and player identity.
- Current and historical roster membership.
- Transfers.
- Placements and standings.
- Patch, tier, date, region, and tournament-level aggregate analysis.

The authenticated API documentation does **not** guarantee a stable sub-schema for:

- Dota 2 hero picks and bans.
- The team or side responsible for draft values.
- First-pick assignment.
- A canonical hero catalog or hero identifier.
- Per-game player-to-hero assignments.
- Player KDA, damage, last hits, denies, GPM, XPM, net worth, or items.
- Team kills, gold, towers, barracks, or Roshan counts.
- Spatial or time-series game telemetry.

Authenticated official API samples now prove that per-team hero slots, ban
slots, sides, game winners, game IDs, patches, and durations are present inside
`match2games`. These are sample-validated nested paths, not v3-guaranteed
subkeys. Explicit first pick and a globally interleaved draft sequence were not
present and must not be inferred.

Therefore:

| Product capability | Verdict |
| --- | --- |
| AI Draft Assistant | **Draft inputs validated with documented first-pick/global-order limitations; coverage audit pending** |
| Player identity and roster analytics | **Approved from documented fields** |
| Player performance analytics | **Blocked pending authenticated Dota match samples** |
| Series-level Match Analytics | **Approved from documented fields** |
| Game-level Match Analytics | **Approved from sample-validated nested fields** |
| Tournament and patch aggregate heatmaps | **Approved from documented fields** |
| Draft synergy/counter heatmaps | **Approved from sample-validated per-team draft fields** |
| Spatial map heatmaps | **Not supported by the documented API** |

No production ingestion or model code should be written until the remaining
historical coverage checks in Section 12 are approved.

## 2. Contract Confidence Levels

Every product field is assigned one of four confidence levels:

| Level | Meaning | Engineering policy |
| --- | --- | --- |
| **L1 — API-guaranteed** | Exact field name and type appear in the authenticated v3 endpoint documentation. | Safe to include in the stable ingestion contract. |
| **L2 — Official nested LPDB field** | The JSON container is L1, and generic nested fields appear in official LPDB documentation, but the v3 API does not type or guarantee its subkeys. | Preserve raw JSON; normalize only through tolerant, versioned adapters. |
| **L3 — Observed, not API-contracted** | Data appears on official Liquipedia Dota pages or editing documentation but has no guaranteed v3 field path. | Do not make it a production requirement without authenticated response samples. |
| **L4 — Unavailable** | No endpoint or documented field supplies the data. | Exclude from scope or obtain explicit approval for another official source. |

## 3. Request Contract

### 3.1 Base Request

| Property | Contract |
| --- | --- |
| Base URL | `https://api.liquipedia.net/api/v3` |
| HTTP method | `GET` only |
| Required query parameter | `wiki=dota2` |
| Authentication | `Authorization: Apikey <secret>` |
| Compression | Client must accept gzip |
| API key policy | Server-side secret; never expose to the frontend or commit to Git |

### 3.2 Common Query Parameters

| Parameter | Type | Contract |
| --- | --- | --- |
| `wiki` | string | Required. Pipe-separated values support authorized multi-wiki calls. |
| `conditions` | string | LPDB condition syntax, for example `[[field::value]]`. |
| `query` | string | Comma-separated projection of returned fields. |
| `limit` | integer | Default `20`; maximum `1000`. |
| `offset` | integer | Default `0`; offset-based pagination. |
| `order` | string | SQL-like ordering, for example `date ASC`. |
| `groupby` | string | SQL-like grouping. |

The `match` endpoint additionally accepts:

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `rawstreams` | string enum: `true`, `false` | `false` | Controls whether stream provider IDs or Liquipedia stream names are returned. |
| `streamurls` | string enum: `true`, `false` | `false` | Controls whether stream URLs are returned. |

### 3.3 Filter Semantics

- Equality: `[[field::value]]`
- Inequality: `[[field::!value]]`
- Less than: `[[field::<value]]`
- Greater than: `[[field::>value]]`
- Boolean composition: `AND`, `OR`, and parentheses
- JSON subkey syntax: append the subkey to the container name with `_`
- Date functions: `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`
- Numeric projection functions: `COUNT`, `SUM`, `AVG`, `MAX`, `MIN`

The authenticated documentation states that JSON subkeys are not guaranteed to exist. Filters that depend on Dota-specific JSON paths are therefore not stable contracts.

## 4. Response Contract

Successful and failed calls return a JSON object with up to three keys:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `result` | array of objects | Yes on a proper call | Query results; may be an empty array. |
| `error` | array of strings | No | Fatal request problems. |
| `warning` | array of strings | No | Non-fatal problems or deprecations. |

Documented HTTP statuses:

| Status | Meaning |
| --- | --- |
| `200` | Successful call |
| `403` | Invalid API key |
| `404` | Requested data does not exist |
| `429` | API limit exceeded |

Important ingestion implications:

- The response has no documented total-count or next-page cursor.
- Pagination completion must be inferred when `result.length < limit`.
- Duplicate records may occur and must be deduplicated by the consumer or reduced with `groupby`.
- There is no documented top-level record revision ID, `updated_at`, ETag, or deletion marker.
- Fields must be treated as nullable or omittable because the docs do not define required response properties.
- A projected `query` intentionally omits non-requested fields.

## 5. Exact Endpoint Field Inventories

These are the exact names and types shown in the authenticated v3 documentation.

### 5.1 `GET /match`

```text
pageid: number
pagename: string
namespace: number
objectname: string
match2id: string
match2bracketid: string
status: string
winner: string
walkover: string
resulttype: string
finished: boolean
mode: string
type: string
section: string
game: string
patch: string
links: json
bestof: number
date: exactdate
dateexact: boolean
stream: json
vod: string
tournament: string
parent: string
tickername: string
shortname: string
series: string
icon: string
iconurl: string
icondark: string
icondarkurl: string
liquipediatier: string
liquipediatiertype: string
publishertier: string
extradata: json
match2bracketdata: json
match2games: json
match2opponents: json
```

Contract notes:

- The authenticated endpoint documentation types `winner` as `string`. Ingestion must preserve the source value before any integer coercion.
- `match2games`, `match2opponents`, `match2bracketdata`, and `extradata` have no authenticated sub-schema.
- Series-level metadata is L1.
- Individual-game data is at best L2 because it is nested under `match2games`.

### 5.2 `GET /player`

```text
pageid: number
pagename: string
namespace: number
objectname: string
id: string
alternateid: string
name: string
localizedname: string
type: string
nationality: string
nationality2: string
nationality3: string
region: string
birthdate: date
deathdate: date
teampagename: string
teamtemplate: string
links: json
status: string
earnings: number
earningsbyyear: json
extradata: json
```

The player endpoint contains identity, biography, current-team, link, status, and earnings data. It contains no documented per-game or performance statistics.

### 5.3 `GET /team`

```text
pageid: number
pagename: string
namespace: number
objectname: string
name: string
locations: json
region: string
logo: string
logourl: string
logodark: string
logodarkurl: string
textlesslogourl: string
textlesslogodarkurl: string
status: string
createdate: date
disbanddate: date
earnings: number
earningsbyyear: json
template: string
links: json
extradata: json
```

### 5.4 `GET /squadplayer`

```text
pagename: string
namespace: number
objectname: string
id: string
link: string
name: string
nationality: string
position: string
role: string
type: string
newteam: string
teamtemplate: string
newteamtemplate: string
status: string
joindate: exactdate
joindateref: json
leavedate: exactdate
leavedateref: json
inactivedate: exactdate
inactivedateref: json
extradata: json
```

This is the strongest documented resource for roster membership, player position, role, status, and membership dates.

### 5.5 `GET /transfer`

```text
pageid: number
pagename: string
namespace: number
objectname: string
staticid: string
player: string
nationality: string
fromteam: string
toteam: string
fromteamtemplate: string
toteamtemplate: string
role1: string
role2: string
reference: json
date: exactdate
wholeteam: boolean
extradata: json
```

### 5.6 `GET /tournament`

```text
pageid: number
pagename: string
namespace: number
objectname: string
name: string
shortname: string
tickername: string
banner: string
bannerurl: string
bannerdark: string
bannerdarkurl: string
icon: string
iconurl: string
icondark: string
icondarkurl: string
seriespage: string
serieslist: json
previous: string
previous2: string
next: string
next2: string
game: string
mode: string
patch: string
endpatch: string
type: string
organizers: string
startdate: date
enddate: date
sortdate: date
locations: json
prizepool: number
participantsnumber: number
liquipediatier: string
liquipediatiertype: string
publishertier: string
status: string
maps: string
format: string
sponsors: string
extradata: json
```

This endpoint supports tournament, patch-range, tier, region/location, format, participant-count, and prize-pool analysis.

### 5.7 `GET /series`

```text
pageid: number
pagename: string
namespace: number
objectname: string
name: string
abbreviation: string
image: string
imageurl: string
imagedark: string
imagedarkurl: string
icon: string
iconurl: string
icondark: string
icondarkurl: string
game: string
type: string
organizers: json
locations: json
prizepool: number
liquipediatier: string
liquipediatiertype: string
publishertier: string
launcheddate: exactdate
defunctdate: exactdate
defunctfate: string
links: json
extradata: json
```

This resource represents tournament series or circuits, not an individual best-of match.

### 5.8 `GET /placement`

```text
pageid: number
pagename: string
namespace: number
objectname: string
tournament: string
series: string
parent: string
imageurl: string
imagedarkurl: string
startdate: exactdate
date: exactdate
placement: string
prizemoney: number
individualprizemoney: number
prizepoolindex: number
weight: number
mode: string
type: string
liquipediatier: string
liquipediatiertype: string
publishertier: string
icon: string
iconurl: string
icondark: string
icondarkurl: string
game: string
lastvsdata: json
opponentname: string
opponenttemplate: string
opponenttype: string
opponentplayers: json
qualifier: string
qualifierpage: string
qualifierurl: string
extradata: json
```

### 5.9 `GET /standingsentry`

```text
pageid: number
pagename: string
namespace: number
objectname: string
parent: string
standingsindex: number
opponenttype: string
opponentname: string
opponenttemplate: string
opponentplayers: json
placement: number
definitestatus: string
currentstatus: string
placementchange: number
scoreboard: json
roundindex: number
slotindex: number
extradata: json
```

The endpoint’s singular route is `/standingsentry`.

### 5.10 `GET /standingstable`

```text
pageid: number
pagename: string
namespace: number
objectname: string
parent: string
standingsindex: number
title: string
tournament: string
section: string
type: string
matches: json
config: json
extradata: json
```

The endpoint’s exact route is `/standingstable`.

### 5.11 `GET /datapoint`

```text
pageid: number
pagename: string
namespace: number
objectname: string
type: string
name: string
information: string
image: string
imageurl: string
imagedark: string
imagedarkurl: string
date: exactdate
extradata: json
```

`datapoint` is a generic miscellaneous resource. The documentation does not state that it provides a complete Dota hero catalog, patch catalog, or match telemetry. It cannot be treated as a guaranteed replacement for those missing resource types.

## 6. Official Generic Nested Match Structure

The authenticated v3 endpoint documents only the JSON containers. The separate official LPDB match documentation describes the following generic nested structure.

### 6.1 `match2games[]` — L2

Officially described generic game fields include:

```text
match2id
match2gameid
subgroup
scores
participants
winner
walkover
resulttype
status
mode
type
game
patch
tournament
date
vod
map
length
parent
extradata
```

The v3 endpoint does not provide a typed schema, nullability rules, or Dota-specific keys for these objects.

### 6.2 `match2opponents[]` — L2

Officially described generic opponent fields include:

```text
match2id
match2opponentid
type
name
template
icon
icondark
score
placement
status
match2players
extradata
```

### 6.3 `match2players[]` — L2

Officially described generic player fields include:

```text
match2id
match2opponentid
match2playerid
name
displayname
flag
extradata
```

### 6.4 `participants` — L2

The official generic documentation describes `participants` as a JSON object keyed by:

```text
<match2opponentid>_<match2playerid>
```

Its values may contain wiki-specific fields. No Dota-specific participant keys are documented or guaranteed by the authenticated v3 contract.

## 7. AI Draft Assistant Field Contract

### 7.1 Required Training and Inference Fields

| Requirement | Candidate source path | Type | Level | Availability verdict |
| --- | --- | --- | --- | --- |
| Series match ID | `match.match2id` | string | L1 | Available |
| Tournament page/reference | `match.parent`, `match.tournament` | string | L1 | Available |
| Tournament series | `match.series` | string | L1 | Available |
| Tournament tier | `match.liquipediatier`, `match.liquipediatiertype`, `match.publishertier` | string | L1 | Available |
| Series date | `match.date` | exactdate | L1 | Available |
| Date precision flag | `match.dateexact` | boolean | L1 | Available |
| Best-of format | `match.bestof` | number | L1 | Available |
| Series completion | `match.finished` | boolean | L1 | Available |
| Series winner | `match.winner` | string | L1 | Available |
| Walkover/invalid-result filter | `match.walkover`, `match.resulttype`, `match.status` | string | L1 | Available |
| Series patch | `match.patch` | string | L1 | Available |
| Individual game ID/index | `match.match2games[*].match2gameid` | undocumented JSON subkey | L2 | Conditionally available |
| Individual game date | `match.match2games[*].date` | undocumented JSON subkey | L2 | Conditionally available |
| Individual game patch | `match.match2games[*].patch` | undocumented JSON subkey | L2 | Conditionally available |
| Individual game duration | `match.match2games[*].length` | undocumented JSON subkey | L2 | Conditionally available |
| Individual game winner | `match.match2games[*].winner` | undocumented JSON subkey | L2 | Conditionally available |
| Team identities | `match.match2opponents[*].name/template` | undocumented JSON subkeys | L2 | Conditionally available |
| Match-time player identities | `match.match2opponents[*].match2players` | undocumented JSON subkey | L2 | Conditionally available |
| Radiant/Dire assignment | `match2games[*].extradata.team1side`, `team2side` | string | L3 | Observed in official API samples |
| First-pick assignment | No observed field | unknown | L4 for validated payload shape | Unavailable; never infer |
| Per-team pick slots | `match2games[*].extradata.team1hero1..5`, `team2hero1..5` | string | L3 | Observed in official API samples |
| Per-team ban slots | `match2games[*].extradata.team1ban1..7`, `team2ban1..7` | string | L3 | Observed in official API samples |
| Global draft action number | No observed field | unknown | L4 for validated payload shape | Unavailable; never infer |
| Global interleaved draft order | No observed field | unknown | L4 for validated payload shape | Unavailable; never reconstruct |
| Draft phase | No observed field | unknown | L4 for validated payload shape | Unavailable |
| Pick/ban team slot | Encoded by `team1*` / `team2*` field name | integer derived from source key | L3 | Available as an explicit source-key component |
| Picked/banned hero identity | Values of `team{1\|2}hero*` / `team{1\|2}ban*` | string | L3 | Observed as hero names |
| Complete hero catalog | No documented v3 hero endpoint | unknown | L4 | Unavailable as a guaranteed resource |
| Hero patch availability | No documented field or endpoint | unknown | L4 | Unavailable |

### 7.2 Draft Assistant Decision

The authenticated validation proves the following ML contract:

```text
label:
  individual_game_winner

features:
  team1hero1 ... team1hero5
  team2hero1 ... team2hero5
  team1ban1 ... team1ban7
  team2ban1 ... team2ban7
  team1side
  team2side
  patch
  date
```

Slot numbers preserve per-team order only. They do not prove global action
order. `first_pick` and `global_draft_sequence` are unavailable inputs and
must remain null/absent rather than synthesized.

The Draft Assistant field shape is approved for subsequent ingestion design.
Production training remains blocked until representative historical coverage,
patch/tier distribution, missingness, and temporal-split suitability are
measured.

## 8. Player Analytics Field Contract

| Requirement | Documented source | Level | Verdict |
| --- | --- | --- | --- |
| Player ID/tag | `player.id` | L1 | Available |
| Alternate ID | `player.alternateid` | L1 | Available |
| Full/localized name | `player.name`, `player.localizedname` | L1 | Available |
| Nationalities and region | `player.nationality*`, `player.region` | L1 | Available |
| Birth/death dates | `player.birthdate`, `player.deathdate` | L1 | Available |
| Current team | `player.teampagename`, `player.teamtemplate` | L1 | Available |
| Status | `player.status` | L1 | Available |
| Career earnings | `player.earnings`, `player.earningsbyyear` | L1/L1 JSON | Available, nested shape untyped |
| Roster position and role | `squadplayer.position`, `squadplayer.role` | L1 | Available |
| Join/leave/inactive dates | `squadplayer.joindate`, `leavedate`, `inactivedate` | L1 | Available |
| Transfer history | `transfer.*` | L1 | Available |
| Tournament placements | `placement.opponentplayers`, `placement.placement` | L1 JSON/L1 | Conditionally linkable |
| Match appearances | Nested `match2players` | L2 | Conditionally available |
| Hero played per game | No guaranteed v3 field path | L3 | Not verified |
| Game result per player | Requires L2 game and participant join | L2/L3 | Not verified end-to-end |
| Kills/deaths/assists | No documented field | L3 | Not verified |
| Hero damage | No documented field | L3 | Not verified |
| Last hits/denies | No documented field | L3 | Not verified |
| GPM/XPM | No documented field | L3 | Not verified |
| Net worth | No documented field | L3 | Not verified |
| Items | No documented field | L3 | Not verified |
| In-game position coordinates | No documented field | L4 | Unavailable |

Identity, roster, transfer, earnings, and placement analytics are approved. Performance analytics remain blocked.

## 9. Match Analytics Field Contract

| Requirement | Source | Level | Verdict |
| --- | --- | --- | --- |
| Series schedule/date | `match.date`, `dateexact` | L1 | Available |
| Series status/result | `status`, `finished`, `winner`, `resulttype`, `walkover` | L1 | Available |
| Best-of and mode | `bestof`, `mode`, `game`, `type` | L1 | Available |
| Tournament context | `tournament`, `parent`, `series`, tier fields | L1 | Available |
| Patch | `patch` | L1 | Available |
| Streams and VOD | `stream`, `vod`, `links` | L1/L1 JSON | Available |
| Opponent names and series scores | `match2opponents` | L2 | Conditionally available |
| Individual game list | `match2games` | L1 JSON container | Available as raw JSON |
| Game winner, date, duration, patch | Generic nested fields | L2 | Conditionally available |
| Players in the series | Nested `match2players` | L2 | Conditionally available |
| Players and heroes in each game | Wiki-specific participant JSON | L3 | Not verified |
| Draft timeline | No guaranteed v3 field path | L3 | Not verified |
| Team game statistics | No documented fields | L3 | Not verified |
| Player game statistics | No documented fields | L3 | Not verified |
| Event timeline | No documented fields | L4 | Unavailable |

Series-level Match Analytics is approved. Rich game-level Match Analytics is not.

## 10. Heatmap and Visualization Contract

| Visualization | Minimum fields | Availability |
| --- | --- | --- |
| Tournament activity by date | Tournament/match date and tournament | L1; approved |
| Tournament activity by region | Tournament locations/region and date | L1 plus untyped `locations`; approved with tolerant parsing |
| Patch usage over time | Match/tournament patch and date | L1; approved |
| Team head-to-head matrix | Match opponents and result | L1 container plus L2 nested opponent fields; conditional |
| Hero pick-rate heatmap | Per-game hero picks and patch | L3; blocked |
| Hero ban-rate heatmap | Per-game hero bans and patch | L3; blocked |
| Hero synergy matrix | Team-side hero picks and outcome | L3; blocked |
| Hero counter matrix | Opposing hero picks and outcome | L3; blocked |
| Player–hero pool matrix | Player-to-hero game assignment | L3; blocked |
| Draft-order heatmap | Ordered draft action, team, hero, action type | L3; blocked |
| Spatial ward/death/farm heatmap | Coordinates and timestamps | L4; unsupported |

## 11. Webhook Contract

The official authenticated webhook documentation defines four events:

```text
delete
edit
move
purge
```

### 11.1 Edit, Delete, and Purge Payload

```json
{
  "page": "Page Name",
  "namespace": 0,
  "wiki": "pathofwiki",
  "event": "event"
}
```

### 11.2 Move Payload

```json
{
  "from_page": "Old Page Name",
  "page": "New Page Name",
  "from_namespace": 0,
  "namespace": 0,
  "wiki": "pathofwiki",
  "event": "move"
}
```

Contract limitations:

- A new page emits an `edit` event.
- The payload identifies a page, not the changed LPDB resource rows.
- No event ID, timestamp, revision ID, signature field, retry policy, or delivery-order guarantee is documented.
- A webhook consumer must re-query relevant endpoints using `pagename` and `namespace`.
- Reconciliation polling remains necessary.

## 12. Required Authenticated Sample-Verification Gate

The documentation contract alone cannot verify Dota-specific JSON fields. Before implementation, execute a small, rate-safe validation set through the authenticated Swagger interface or API client.

Do not paste the API key into source files, Markdown, chat, logs, shell history, or request URLs.

The repository provides a two-step discovery and validation gate:

```text
scripts/discover_liquipedia_samples.py
scripts/validate_liquipedia_api.py
```

Discovery performs exactly four bounded, non-paginated `GET /v3/match`
requests and then stops for human review. The four requests identify recent
completed, older completed, future unfinished, and exceptional-result
candidates; the recent response is also inspected locally for a multi-game
series with changing side assignments. Requests are spaced by 61 seconds,
never retried automatically, and return at most eight records each.

After the selected IDs are approved, the validation utility combines them into
one exact-`match2id`, projected `GET /v3/match` request. It saves the
decompressed response body and performs all nested-field analysis locally.
The complete successful gate therefore consumes five requests: four discovery
requests plus one separately approved validation request.

There are no implicit default IDs. The validator requires either explicit
`--match-id` arguments or the reviewed `selection.json` produced by discovery.
Generated artifacts are stored under the Git-ignored
`data/validation/liquipedia/` directory.

### 12.1 Required Match Samples

Discover and validate at least:

1. One recent completed professional match whose official page displays full drafts and player performance.
2. One older completed match; report whether its payload shape differs rather than assuming that age proves a legacy representation.
3. One upcoming or incomplete match.
4. One walkover, forfeit, cancelled, or not-played match.
5. One match spanning multiple games with different Radiant/Dire assignments.

The official v3 contract has no documented legacy-schema flag and does not
guarantee filterable nested draft or side-assignment subkeys. Accordingly:

- the older category uses a fixed 2018 date window;
- full-draft and side-change properties are proven by local inspection of
  returned `match2games`, never by an undocumented server-side condition;
- unresolved categories stop the gate without extra calls or guessed IDs;
- a fallback ID is acceptable only with recorded official-API provenance and
  separate approval.

Project only:

```text
pageid
pagename
namespace
objectname
match2id
status
winner
walkover
resulttype
finished
patch
date
dateexact
bestof
tournament
parent
series
liquipediatier
extradata
match2games
match2opponents
```

### 12.2 Paths That Must Be Proven

For each sample, record whether the response provides stable paths for:

```text
individual game ID
individual game winner
individual game patch
individual game duration
external Dota match ID
team identities
player identities
Radiant/Dire assignment
first-pick assignment
ordered picks
ordered bans
hero identity
player-to-hero assignment
K/D/A
hero damage
last hits/denies
GPM/XPM
net worth
items
team kills/gold/towers/barracks/Roshans
```

### 12.3 Coverage Checks

After paths are identified, use aggregate or sampled queries to measure:

- Percentage of completed games with a known per-game winner.
- Percentage with exactly five picks per side.
- Percentage with a complete ordered draft.
- Percentage with both side assignments.
- Percentage with player-to-hero mappings.
- Percentage with each performance statistic.
- Coverage by year, patch, and tournament tier.
- Frequency and shape of legacy versus current JSON structures.

### 12.4 Approval Rule

The Draft Assistant schema gate passes because:

- Game outcome, side, hero, and ordered draft paths are found.
- Eight recent payloads agree on the observed normalizable per-team structure.
- The project preserves the complete raw JSON and treats nested keys as schema-versioned, optional inputs.

The following gates remain open:

- Historical coverage must be sufficient for temporal model evaluation.
- The older sample lacks the complete recent ban shape and therefore requires
  versioned adapters plus coverage measurement.
- Player performance analytics can proceed only for metrics whose paths and
  coverage are independently proven.

## 13. Canonical Database Impact

The following tables are approved from L1 fields:

```text
tournament_series
tournaments
matches
players
teams
roster_memberships
transfers
placements
standings
standing_entries
source_record_versions
ingestion_runs
ingestion_checkpoints
api_request_ledger
data_quality_issues
```

The following tables are now supported by sample-validated L3 draft fields,
but must use versioned tolerant adapters:

```text
games
game_teams
game_draft_picks
game_draft_bans
```

The following tables remain provisional or unsupported pending independent
verification:

```text
game_participants
game_participant_items
game_team_stats
heroes
hero_aliases
hero_patch_availability
```

A global `draft_actions` table is not supported by the validated payload
because neither first pick nor an interleaved action sequence is available.

All L2 and L3 extraction must:

- Preserve the original JSON.
- Record the observed JSON path and adapter version.
- Tolerate missing and additional keys.
- Quarantine structurally invalid records.
- Never silently default missing competitive fields.

## 14. Final Milestone 1 Decision

The exact authenticated documentation supports the platform’s identity,
roster, tournament, series-level match, placement, standings, and
patch-context foundations.

Authenticated official API samples additionally prove a normalizable
per-team Dota draft shape with hero slots, ban slots, sides, outcomes, game
IDs, patches, and durations. Explicit first pick and global draft order are
unavailable and excluded from the contract.

The field-shape gate for the flagship Draft Assistant is complete with those
limitations. Historical coverage, hero-name normalization, and detailed
player-performance availability remain inside Milestone 1 and must be approved
before database or model implementation begins.

## 15. Official Documentation

Authenticated documentation:

- [LiquipediaDB API v3](https://api.liquipedia.net/documentation/api/v3)
- [LiquipediaDB v3 OpenAPI](https://api.liquipedia.net/documentation/api/v3/openapi)
- [Match endpoint](https://api.liquipedia.net/documentation/api/v3/match)
- [Player endpoint](https://api.liquipedia.net/documentation/api/v3/player)
- [Team endpoint](https://api.liquipedia.net/documentation/api/v3/team)
- [Squad Player endpoint](https://api.liquipedia.net/documentation/api/v3/squadplayer)
- [Transfer endpoint](https://api.liquipedia.net/documentation/api/v3/transfer)
- [Tournament endpoint](https://api.liquipedia.net/documentation/api/v3/tournament)
- [Series endpoint](https://api.liquipedia.net/documentation/api/v3/series)
- [Placement endpoint](https://api.liquipedia.net/documentation/api/v3/placement)
- [Standings Entry endpoint](https://api.liquipedia.net/documentation/api/v3/standingsentry)
- [Standings Table endpoint](https://api.liquipedia.net/documentation/api/v3/standingstable)
- [Datapoint endpoint](https://api.liquipedia.net/documentation/api/v3/datapoint)
- [Webhook documentation](https://api.liquipedia.net/documentation/webhook)

Additional official LPDB documentation:

- [LiquipediaDB overview](https://liquipedia.net/commons/Help%3ALiquipediaDB)
- [LiquipediaDB match structure](https://liquipedia.net/commons/Help%3ALiquipediaDB/Match)
- [Dota 2 tournament-result and draft storage](https://liquipedia.net/dota2/Liquipedia%3AUpdating_tournament_results)
