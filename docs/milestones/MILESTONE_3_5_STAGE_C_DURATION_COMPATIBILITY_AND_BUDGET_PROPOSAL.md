# Milestone 3.5 Stage C: Duration Compatibility Review and Budget Proposal

> Read-only compatibility review of the four remaining duration values in the
> immutable `2024-Q1` cache, plus a credential-free proposal for extending
> only the request budget of an oversized historical partition.

Status: **review complete; no compatibility or acquisition change implemented**
Report date: 2026-07-28
Campaign: `m3_5_20220101_20260727_e2c4c37a9792`
Authenticated API requests made by this review: **0**
Parser changes made by this review: **0**
Acquisition-policy changes made by this review: **0**

## 1. Outcome

None of the four literals is an officially documented Liquipedia
`match2game.length` sentinel or alternate duration grammar.

- The two `"<s>Game 3</s>"` values and `"<s>Game 5</s>"` are presentation
  markup in a semantic duration field. Their surrounding objects establish
  that they represent unused game slots, but Liquipedia does not document
  these strings as official duration placeholders.
- `"7m04"` belongs to a completed game and is duration-like. It is probably a
  suffix-omitted form of `"7m04s"`, but that meaning is not documented and
  converting it to 424 seconds would be an inference.

The recommended compatibility policy is deliberately conservative:

1. preserve every original value in immutable raw provenance;
2. treat the three struck-through labels as unavailable durations only
   through a future exact, context-checked compatibility rule;
3. keep `"7m04"` unavailable rather than inferring 424 seconds; and
4. keep all four games out of the supervised draft dataset under the existing
   eligibility rules.

No recommendation requires broad HTML stripping, permissive duration parsing,
or a change to the supervised target or feature contract.

For the acquisition stop, the recommended budget change is a targeted
`2024-Q1` amendment from 8 to 20 page slots. The first eight request identities
remain cache hits, so the amendment authorizes at most twelve new HTTP
attempts: offsets 800 through 1900. The default budget for every other
historical quarter remains 8.

## 2. Evidence boundary and provenance

All four objects occur in the same cached official API response:

| Field | Value |
| --- | --- |
| Endpoint | `https://api.liquipedia.net/api/v3/match` |
| Run ID | `m3_20240101_20240401_4aa59da8deab` |
| Request sequence | 8 |
| Offset | 700 |
| Request hash | `0aaa6401beda7eff4b54e513f73a84b8d903ecff8080aaf6ab9801cf89bc7ff1` |
| Response SHA-256 | `91b61bbd141d3841af969b12af2623b4166d7c28ab140134311d317fe7e69220` |
| HTTP status | 200 |
| Record count | 100 |
| Response bytes | 409,961 |
| Acquired at | `2026-07-28T13:36:27.771415+00:00` |
| Cache metadata state | `successful_validated_response` |

The response checksum was recomputed locally and matches the immutable cache
metadata and checkpoint.

A cache-wide offline scan covered 48 cached responses and 8,774 game objects.
It found exactly these four values rejected by the current strict duration
normalizer and no others.

In each case below, “complete source JSON object” means the complete
`match2games[*]` object containing `length`, reproduced without removing or
adding fields. JSON whitespace and indentation are presentation-only.

## 3. Official contract evidence

The reviewed official material establishes the following:

- [LiquipediaDB Match documentation](https://liquipedia.net/commons/Help%3ALiquipediaDB/Match)
  defines game length as a game field but does not publish literal duration
  sentinels or a value grammar. It documents non-played/default semantics in
  fields such as `status`, `resulttype`, `walkover`, `finished`, and `winner`.
- [The official generic match input types](https://github.com/Liquipedia/Lua-Modules/blob/4ff4ea40be5b565ea8e62133897ced00f83ba4f1/lua/wikis/commons/MatchGroup/Util.lua#L219-L257)
  allow `length` to be a number or string without defining string semantics.
- [The official Dota 2 normal-input module](https://github.com/Liquipedia/Lua-Modules/blob/4ff4ea40be5b565ea8e62133897ced00f83ba4f1/lua/wikis/dota2/MatchGroup/Input/Custom/Normal.lua#L20-L24)
  stores the supplied length value verbatim.
- [The official Dota 2 MatchPage input module](https://github.com/Liquipedia/Lua-Modules/blob/4ff4ea40be5b565ea8e62133897ced00f83ba4f1/lua/wikis/dota2/MatchGroup/Input/Custom/MatchPage.lua#L41-L52)
  formats a numeric duration as minutes and two-digit seconds, otherwise
  falling back to the raw supplied length.
- [The official unplayed-input handling](https://github.com/Liquipedia/Lua-Modules/blob/4ff4ea40be5b565ea8e62133897ced00f83ba4f1/lua/wikis/commons/MatchGroup/Input/Util.lua#L73-L78)
  recognizes unplayed values in result-oriented inputs rather than defining
  them as duration strings.
- [Liquipedia's Dota 2 result-update examples](https://liquipedia.net/dota2/Liquipedia%3AUpdating_tournament_results)
  show canonical manual values such as `35m44s`, `27m14s`, and `56m04s`,
  while unused maps have empty result and length fields or use a separate skip
  signal.

Therefore the report does not call any reviewed literal an “official
Liquipedia duration sentinel.” This also clarifies the existing exact
`length == "Default"` behavior: it is a project compatibility policy based on
an observed official API payload, not a documented duration grammar.

## 4. Individual compatibility review

### 4.1 `D8VM7QJos8_R04-M001`, game 3

| Field | Value |
| --- | --- |
| Exact JSON path | `result[92].match2games[2].length` |
| Exact original value | `"<s>Game 3</s>"` |
| Series | finished best-of-three solo series |
| Final score | 0–2 |
| Earlier games | games 1 and 2 have winners, scores, sides, publisher IDs, and valid durations |
| Object state | no winner, score, side, or publisher ID |

Complete source JSON object:

```json
{
  "map": "",
  "subgroup": "",
  "match2gameid": 3,
  "scores": [],
  "participants": {
    "1_1": [],
    "2_1": []
  },
  "opponents": [
    {
      "players": [
        []
      ]
    },
    {
      "players": [
        []
      ]
    }
  ],
  "status": "",
  "winner": "",
  "walkover": "",
  "resulttype": "",
  "date": "2024-02-10 11:20:00",
  "mode": "solo",
  "type": "Offline",
  "game": "dota2",
  "patch": "",
  "vod": "",
  "length": "<s>Game 3</s>",
  "extradata": {
    "team1objectives": [],
    "dateexact": true,
    "team1hero1": "Queen of Pain",
    "timestamp": 1707564000,
    "team2hero1": "Queen of Pain",
    "team2objectives": []
  }
}
```

Classification:

**Unexpected presentation-markup payload with context-confirmed unplayed-slot
semantics.** It is not an officially documented `length` placeholder. The
unplayed interpretation follows from the already-decided 2–0 series, absent
game result data, absent sides and publisher ID, and agreement between
`Game 3` and `match2gameid = 3`.

Recommended handling:

- Preserve the raw value.
- If approved later, recognize this exact placeholder only when the game
  number matches `match2gameid`, the series is already decided, and winner,
  score, sides, and publisher ID are absent.
- Normalize duration to missing, never to `3` or another inferred duration.
- Let the existing earlier eligibility failures exclude the non-game slot.

### 4.2 `D8VM7QJos8_R04-M003`, game 3

| Field | Value |
| --- | --- |
| Exact JSON path | `result[93].match2games[2].length` |
| Exact original value | `"<s>Game 3</s>"` |
| Series | finished best-of-three solo series |
| Final score | 2–0 |
| Earlier games | games 1 and 2 are populated completed games |
| Object state | no winner, score, side, or publisher ID |

Complete source JSON object:

```json
{
  "map": "",
  "subgroup": "",
  "match2gameid": 3,
  "scores": [],
  "participants": {
    "1_1": [],
    "2_1": []
  },
  "opponents": [
    {
      "players": [
        []
      ]
    },
    {
      "players": [
        []
      ]
    }
  ],
  "status": "",
  "winner": "",
  "walkover": "",
  "resulttype": "",
  "date": "2024-02-10 12:05:00",
  "mode": "solo",
  "type": "Offline",
  "game": "dota2",
  "patch": "",
  "vod": "",
  "length": "<s>Game 3</s>",
  "extradata": {
    "team1objectives": [],
    "dateexact": true,
    "team1hero1": "Crystal Maiden",
    "timestamp": 1707566700,
    "team2hero1": "Crystal Maiden",
    "team2objectives": []
  }
}
```

Classification:

**Unexpected presentation-markup payload with context-confirmed unplayed-slot
semantics.** It is the same observed shape as the first case, but is reviewed
independently. The series result is 2–0 and the unused object lacks every
normal played-game signal.

Recommended handling:

- Preserve the raw value.
- Apply the same future exact and contextual missing-value rule only after
  explicit approval.
- Do not generalize this into arbitrary HTML stripping.
- Do not interpret the embedded game number as elapsed time.

### 4.3 `D8VM7QJos8_R05-M002`, game 3

| Field | Value |
| --- | --- |
| Exact JSON path | `result[96].match2games[2].length` |
| Exact original value | `"7m04"` |
| Series | finished best-of-three solo series |
| Final score | 2–1 |
| Sibling durations | `"15m00s"` and `"9m28s"` |
| Object state | winner, score, sides, and publisher ID present |

Complete source JSON object:

```json
{
  "map": "",
  "subgroup": "",
  "match2gameid": 3,
  "scores": [
    1,
    0
  ],
  "participants": {
    "1_1": [],
    "2_1": []
  },
  "opponents": [
    {
      "status": "S",
      "score": 1,
      "players": [
        []
      ]
    },
    {
      "status": "S",
      "score": 0,
      "players": [
        []
      ]
    }
  ],
  "status": "",
  "winner": "1",
  "walkover": "",
  "resulttype": "",
  "date": "2024-02-10 14:45:00",
  "mode": "solo",
  "type": "Offline",
  "game": "dota2",
  "patch": "",
  "vod": "",
  "length": "7m04",
  "extradata": {
    "dateexact": true,
    "publisherid": 7579725073,
    "team2objectives": [],
    "team1side": "radiant",
    "team1objectives": [],
    "team1hero1": "Puck",
    "timestamp": 1707576300,
    "team2hero1": "Puck",
    "team2side": "dire"
  }
}
```

Classification:

**Unexpected malformed duration-like payload, not a documented alternate
format and not a placeholder.** The object is a completed game. The sibling
format strongly suggests a missing trailing `s`, but the official contract
does not establish that interpretation.

Recommended handling:

- Preserve `"7m04"` in immutable raw provenance.
- Do not convert it to 424 seconds without official confirmation or a
  corrected upstream value.
- Under a future approved compatibility policy, represent the normalized
  duration as missing and record the unsupported raw value as an anomaly
  rather than failing the entire partition.
- Do not add a broad `NmSS` parser rule at this time.
- This is a one-versus-one game with one hero per side and no bans, so it
  remains ineligible for the five-player supervised draft dataset regardless
  of duration handling.

### 4.4 `D8VM7QJos8_R06-M001`, game 5

| Field | Value |
| --- | --- |
| Exact JSON path | `result[97].match2games[4].length` |
| Exact original value | `"<s>Game 5</s>"` |
| Series | finished best-of-five solo series |
| Final score | 3–1 |
| Earlier games | games 1 through 4 are populated completed games |
| Object state | no winner, score, side, or publisher ID |

Complete source JSON object:

```json
{
  "map": "",
  "subgroup": "",
  "match2gameid": 5,
  "scores": [],
  "participants": {
    "1_1": [],
    "2_1": []
  },
  "opponents": [
    {
      "players": [
        []
      ]
    },
    {
      "players": [
        []
      ]
    }
  ],
  "status": "",
  "winner": "",
  "walkover": "",
  "resulttype": "",
  "date": "2024-02-10 16:05:00",
  "mode": "solo",
  "type": "Offline",
  "game": "dota2",
  "patch": "",
  "vod": "",
  "length": "<s>Game 5</s>",
  "extradata": {
    "team1objectives": [],
    "dateexact": true,
    "team1hero1": "Crystal Maiden",
    "timestamp": 1707581100,
    "team2hero1": "Crystal Maiden",
    "team2objectives": []
  }
}
```

Classification:

**Unexpected presentation-markup payload with context-confirmed unplayed-slot
semantics.** The 3–1 series had already ended, and the unused fifth object has
no played-game result data.

Recommended handling:

- Preserve the raw value.
- If approved later, map it to missing only under the same exact contextual
  checks as the two Game 3 cases.
- Never treat the embedded `5` as a duration.
- Keep the object in normalized audit data and out of supervised training.

## 5. Compatibility decision matrix

| Case | Official placeholder? | Official alternate duration? | Best classification | Recommended normalized duration |
| --- | --- | --- | --- | --- |
| `R04-M001`, game 3 | No documented support | No | unexpected markup; inferred unplayed slot | missing, only after exact contextual approval |
| `R04-M003`, game 3 | No documented support | No | unexpected markup; inferred unplayed slot | missing, only after exact contextual approval |
| `R05-M002`, game 3 | No | No documented support | malformed duration-like payload from a played game | missing; do not infer 424 seconds |
| `R06-M001`, game 5 | No documented support | No | unexpected markup; inferred unplayed slot | missing, only after exact contextual approval |

The safest future implementation is not “more permissive duration parsing.”
It is a small compatibility boundary that separates known non-duration
presentation values and malformed source values from canonical durations,
retains their raw provenance, and prevents one ineligible solo game from
blocking an otherwise usable partition.

## 6. Per-partition request-budget proposal

### 6.1 Current state

| Field | Current value |
| --- | --- |
| Partition | `2024-Q1` |
| Date range | `[2024-01-01T00:00:00Z, 2024-04-01T00:00:00Z)` |
| Existing run | `m3_20240101_20240401_4aa59da8deab` |
| Existing partition ceiling | 8 page slots |
| Accepted pages | 8 |
| Records per accepted page | 100 |
| Records cached | 800 |
| Terminal page reached | no |
| Next sequence / offset | 9 / 800 |
| Stage B + Stage C campaign attempts used | 46 of 100 |
| Campaign attempts remaining | 54 |

The eight successful page identities and response bytes remain immutable.
The existing run should remain `budget_exhausted` as historical evidence; its
configuration and SQLite rows should not be rewritten.

### 6.2 Recommended amendment

Add a **targeted partition override** for `2024-Q1`:

```text
default historical partition page-slot ceiling: 8
2024-Q1 amended page-slot ceiling:             20
incremental page slots:                         12
maximum new HTTP attempts:                      12
```

Do not change the default ceiling globally. A global 20-page configuration
would unnecessarily change every historical partition identity and expand
the campaign from 144 to 360 logical historical request slots.

The larger Q1 ceiling is evidence-based rather than arbitrary. Its 800 cached
records span only `2024-01-03 03:00:00` through
`2024-02-11 09:00:00`, leaving almost seven weeks of the quarter. A simple
linear projection suggests approximately 1,760–1,810 records. This is only a
planning heuristic—January qualifier density may not repeat—but it makes a
12-page ceiling likely to trigger another avoidable review, while 16 pages
still cannot prove completeness above 1,600 records. Twenty page slots provide
a bounded cushion and do not create calls after the first short page.

The proposed amended `BackfillConfig` identity is:

| Field | Proposed value |
| --- | --- |
| Configuration hash | `2c59812252db906c8b373ec33fbc9b5cec0bb3f06e7b7c3250eafd94e442d097` |
| Run ID | `m3_20240101_20240401_2c59812252db` |
| Page size | 100, unchanged |
| Endpoint, conditions, projection, ordering | unchanged |
| Tiers | 1 and 2, unchanged |
| Automatic retries | 0, unchanged |
| Request interval | 67 seconds, unchanged |
| Rolling-hour limit | 54, unchanged |

Because `max_requests` participates in the immutable run identity, the
amended run must be new. It must explicitly reference the exhausted run as
its predecessor. It must not mutate the predecessor's config hash or status.

### 6.3 Exact amended request slots

The first eight request hashes are identical to the verified cache and must
be consumed as cache hits. Only these twelve new slots may reach the network:

| Sequence | Offset | Request hash | Execution condition |
| ---: | ---: | --- | --- |
| 9 | 800 | `c7aa370982768a22974e7ced7438bd7079e24f785f48a4a76f1a71a6eebc2b7a` | page 8 is verified full |
| 10 | 900 | `28021996ccd458493d6c4611100488a0eb88bd9e1e54a814c0fe4cea74a8d284` | page 9 returns exactly 100 |
| 11 | 1000 | `10b7c4293e05c5a03b6297acbe544ffbcf538c439ee26e83912a0080474cfc07` | page 10 returns exactly 100 |
| 12 | 1100 | `bcb63899ace7fbdb005757cd7e980772ef271f4e1202d43a421886a41849567d` | page 11 returns exactly 100 |
| 13 | 1200 | `aef3466e4e0dd7fc709dbf29900101e240bb77ad70c000bde5868d40017aed6b` | page 12 returns exactly 100 |
| 14 | 1300 | `27ea74b9725cd22200f35cbf31e58a2374040a1d15f988cf224d3893c58b0a86` | page 13 returns exactly 100 |
| 15 | 1400 | `19ba999550d6b20ce769ad78471cedd2f5e30c9fe91467fb706590017501cc09` | page 14 returns exactly 100 |
| 16 | 1500 | `9c7897acab8b77dc413f5cfa4822d204d5ade4809c1d3b6798fdec627c76218d` | page 15 returns exactly 100 |
| 17 | 1600 | `5ae3c150bf9d8e33b77f9b2df24a3c72e8342414736b59db4a37eaf19728d810` | page 16 returns exactly 100 |
| 18 | 1700 | `80f55a31ae912a2ca07d13ef89074d566360a237ed63fe14ca7659bf13ce5a10` | page 17 returns exactly 100 |
| 19 | 1800 | `8adbac5f97875c5c6a55a17e30827b075e9c350e8f0c5c0ed73330aef706db67` | page 18 returns exactly 100 |
| 20 | 1900 | `289251a3b442f0452e78698d941fece552912f7e9021819690707e36956a7636` | page 19 returns exactly 100 |

The exact request parameters remain:

```json
{
  "wiki": "dota2",
  "conditions": "([[liquipediatier::1]] OR [[liquipediatier::2]]) AND [[finished::1]] AND [[date::>2023-12-31 23:59:59]] AND [[date::<2024-04-01 00:00:00]]",
  "query": "pageid,pagename,namespace,objectname,match2id,status,winner,walkover,resulttype,finished,patch,date,dateexact,bestof,tournament,parent,series,liquipediatier,extradata,match2games,match2opponents",
  "limit": 100,
  "order": "date ASC, match2id ASC",
  "rawstreams": "false",
  "streamurls": "false"
}
```

Only `offset` varies as shown in the table.

### 6.4 Accounting and resume rules

The campaign coordinator needs a small amendment record, not a new
acquisition architecture:

1. Reference the immutable base campaign ID and fingerprints.
2. Record `2024-Q1` as the only overridden partition.
3. Reference predecessor run
   `m3_20240101_20240401_4aa59da8deab`.
4. Verify all eight predecessor request hashes, response hashes, record
   counts, and cache files before allowing execution.
5. Create the amended run without copying or rewriting response bytes.
6. Reaccept sequences 1–8 from immutable cache.
7. Count the predecessor's 8 HTTP attempts once in campaign accounting.
8. Count only actual new network attempts from the amended run; cache hits
   remain free.
9. Assemble only the completed amended run. Do not concatenate predecessor
   and amended snapshots.
10. Preserve chronological blocking: `2024-Q2` remains unavailable until the
    amended `2024-Q1` run is complete and passes every downstream gate.

If all twelve new slots are used, campaign accounting becomes:

| Metric | Before amendment | Maximum after amendment |
| --- | ---: | ---: |
| Milestone 3.5 attempts used | 46 | 58 |
| Milestone 3.5 attempts remaining | 54 | 42 |
| Complete SQLite HTTP-attempt rows, including pilot | 48 | 60 |

The amended run must fail preflight if any of the first eight cache entries is
missing or differs from its recorded hash. That invariant is what makes the
maximum new network exposure exactly twelve rather than “up to twenty.”

### 6.5 Stop behavior

- Stop complete as soon as a page contains fewer than 100 records.
- Stop immediately on HTTP 403, HTTP 429, malformed JSON, API-level error,
  request-contract conflict, lineage conflict, or rolling-hour violation.
- Stop `budget_exhausted` again if sequence 20 contains 100 records.
- Do not automatically extend beyond 20.
- Do not move to `2024-Q2` until `2024-Q1` passes raw, assembly,
  normalization, supervised, lineage, eligibility, and test gates.
- Do not execute the amendment until the four duration cases have an approved
  compatibility decision.

## 7. Why this is simpler than the alternatives

A targeted 8 → 20 amendment is preferable to:

- changing every historical partition to 20 requests;
- mutating the existing SQLite run configuration;
- silently treating the old eight attempts as free;
- splitting `2024-Q1` into new date ranges and introducing new boundary and
  deduplication questions; or
- adding automatic adaptive pagination.

It preserves the existing API client, request builder, cache, checkpoint,
rate limiter, parser, normalizer, supervised builder, and validation gates.
Only the campaign coordinator needs a thin, auditable exception mechanism and
correct carry-forward accounting.

For future large quarters, keep 8 as the default and prepare an evidence-based,
partition-specific ceiling only after the eighth page is verified full. The
amendment must remain within the unchanged campaign budget and always requires
explicit review; it is not an automatic adaptive-pagination policy.

## 8. Approval boundary

This report is evidence and design only.

It does **not** authorize:

- treating any of the four values as a supported duration;
- changing `parse_duration_seconds`;
- converting `"7m04"` to 424 seconds;
- stripping HTML or markup from arbitrary values;
- changing game eligibility or exclusion ordering;
- modifying campaign state or the SQLite ledger;
- making an authenticated request;
- starting `2024-Q2`; or
- starting Stage D.

Before implementation, the project needs two independent approvals:

1. the recommended value-specific compatibility behavior; and
2. the targeted `2024-Q1` 8 → 20 page-slot amendment with at most twelve new
   authenticated attempts.
