# Evals

Twenty questions, run against the live providers through the server's own
tools, on 2026-08-30. Every call and every response is in `log/qNN.jsonl`,
including the ones that went nowhere. `questions.md` holds the questions, which
were written before any of them was run.

The point is not the score. It is the dead ends: the places where a capable
agent, following the discovery order the instructions prescribe, cannot get
from a reasonable question to an answer. Almost none of what follows is a
crash. The server returns 200 and a well-formed response, and the agent is
still stuck, which is the failure mode this project exists to be about.

## Result

| | |
|---|---|
| Answered | 13 |
| Partial | 3 |
| Blocked | 4 |
| Tool calls | 46 |
| Provider time | 74s |
| Bytes returned | 68KB |

One of the four blocked is not the server's fault: HKMA was returning 502 on
every path during the run, which the README documents as its failure mode.

What worked, and worked well: the FX conventions (3 and 4), point-in-time
revisions (11 and 12), entity lookup by native-script name (13 and 14), and
period normalisation on the non-SDMX adapters (17 and 19). Question 11 asked
whether the IMF had revised Japan's 2024 GDP and one call answered it, with the
vintage that does not carry the key reported as such rather than counted as
agreeing. That is the thing no other free source does.

## Findings

Ordered by how much they cost an agent, worst first.

### 1. An empty response says nothing at all

Three different mistakes returned byte-identical responses:

```json
{"key": {}, "columns": ["period", "value"], "series": [], "total": 0}
```

A currency dimension the flow does not populate, an aggregate that carries no
such series, and a two-code key where one code is empty. The response does not
name which dimension matched nothing. It does not even echo the key that was
asked for, so the agent cannot see what it just failed to get.

The cause of the missing echo is small: `_pack` derives the invariant key by
looking at the frame, and an empty frame has no columns, so the requested key
is dropped rather than returned. Passing the request through would fix the
echo. Saying which dimension is empty needs a probe per dimension, which is
worth its cost only because the alternative is the agent guessing.

Diagnosing it in question 9 took three further calls that a person had to
design. An agent would more likely conclude the data does not exist.

### 2. Codes are returned where the labels are already known

`fetch_data` resolves codes to labels for units and returns raw codes for
everything else. Four questions ran into it:

- Japan's GDP came back as `634751300000000.0` with `units: {"SCALE": "Units"}`
  and no currency anywhere. The currency is in the key, as
  `TYPE_OF_TRANSFORMATION: "XDC"`. This is the README's own headline example of
  a number that is not an answer.
- Singapore's CPI came back as 15 series keyed `SERIES: "1"`, `"1.0"`,
  `"1.01"`, hierarchy positions with no names. Asking `search_codes` for the
  same dimension returns `{"id": "1", "name": "All Items", "unit": "Index"}`.
  The labels exist and the fetch path already performs exactly this lookup to
  resolve units.
- The BIS wildcard returned 38 series keyed by `REF_AREA` code, so answering a
  question about Asia meant mapping 38 codes back by hand.
- IMF CPI returned `COICOP_1999: "CP01"` and
  `TYPE_OF_TRANSFORMATION: "POP_PCH_PA_PT"`, which have to be looked up before
  the numbers mean anything.

### 3. Entity search does not rank, and the first hit is often wrong

`find_entity("Banco Santander")` returns 41 hits. The first is
`EDUARDO R FERNANDEZ PEREZ SL`, an unrelated company that matches because
Santander is also a Spanish city. Filtered to `ES` there are five hits and
Banco Santander S.A. is **last**, behind a mutual society, Banco Banif and a
foundation.

GLEIF's fulltext order is passed through untouched. An agent that takes
`hits[0]` for a common name gets the wrong company with a 200 status. The
server has everything it needs to rank locally: exact legal-name match first,
then prefix, then contains.

### 4. Dataflow search is a contiguous substring match

`find_dataflows("IMF_DATA", "national accounts")` returns `total: 1` and hides
`ANEA`, whose name is "National Economic Accounts (NEA), Annual Data".
`"accounts"` alone returns 17. Two words is the natural thing to type, and it
silently narrows to almost nothing behind a total that reads as authoritative.
Splitting the query and requiring every token would fix it.

### 5. Search does not narrow when it matters

`find_dataflows("ILO", "unemployment")` returns 108 flows, 40 shown, with names
like "LU2: Combined rate of time-related underemployment and unemployment for
persons ages 25 to 54 by sex, household type and presence of children". Nothing
marks which is the headline rate and there is no ranking, so the agent reads
108 names or guesses. Question 7 and question 20 both died here.

`find_dataflows("IMF_DATA", "unemployment")` returns `total: 0` with no
suggestion that another provider might have it.

### 6. There is no way to find a key that exists

`BBSIS` has 15 key dimensions with 6, 3, 17, 20, 219, 26, 4, 31, 72, 7, 10, 1,
2, 1 and 1 codes: 4.36e13 combinations. Pinning one through the prescribed path
means 15 `search_codes` calls and then a guess, with an empty response as the
only signal when the guess is wrong. The README lists "data needs a pinned key"
as a Bundesbank quirk. The tools offer no way to get one.

SDMX answers exactly this with `detail=serieskeysonly`, which returns the keys
that exist and no observations. A tool over it would turn the guess into a
lookup, using a request shape the server already makes.

### 7. The most useful query shapes are undocumented

Both of these work and neither is mentioned anywhere an agent can see:

- `{"REF_AREA": "JP+XM"}` asks for two codes in one request. The `fetch_data`
  description shows one code per dimension, so an agent pays for one download
  per country.
- Leaving a dimension out of the key is a wildcard. This is the single most
  useful shape in the server, because it answers "which countries have this"
  in one call, and question 10 was only solved by trying it on a hunch.

### 8. `direct_children` truncates silently

It asks GLEIF for `page[size]=50` and returns what arrives, with no total and
no truncation flag. `find_entity` reports the provider's total; this does not.
Toyota has 11 children so question 14 is answered correctly, but a company with
200 would return 50 that read as all of them. This is the same failure the
observation truncation fix was written for.

### 9. Vintages crowd out the flow they are vintages of

Four of the ten hits for "consumer price" on IMF are `CPI_2026_*_VINTAGE`, and
the current `CPI` flow sits among them rather than above them. `list_vintages`
exists for exactly this and `find_dataflows` does not point at it.

### 10. The FX tools disagree about provenance

`fx_spot` states the fixing, marks a derived cross and explains the division.
`fx_period_rate` returns the same underlying numbers with the source named and
none of the caveats: no "fixing rather than traded rate", and no warning that a
period end which was not a TARGET business day is the last publication before
it. It also passes through `UNIT_INDEX_BASE: "99Q1=100"` beside a rate of
163.06, which invites reading a rate as an index.

### 11. A provider outage is a raw HTTP string

HKMA's 502 reaches the agent as
`502 Server Error: Bad Gateway for url: https://...?pagesize=1`. Nothing
separates "this provider is down, try another" from "your query was wrong". The
unknown-provider error, by contrast, lists every valid provider and is
recoverable.

### 12. Aggregates and members are unmarked

`G998 European Union (EU)` and `U150 Europe` sit in the same `COUNTRY` codelist
as `FRA`, and `search_codes` does not mark which entries are aggregates. The
instructions warn that summing both double-counts; the tools give no way to
tell them apart beyond noticing that `G998` is not an ISO3 code.

### 13. BIS prints to stdout mid-call

The first BIS fetch of a process writes `sdmx1`'s parse diagnostics to standard
output, including the entire raw `DataSet` XML. It survives `2>/dev/null`, so
it is stdout and not stderr. The README asserts the MCP SDK claims that
descriptor and diverts it. Nothing tests the assertion, and if it is wrong the
JSON-RPC stream is corrupted mid-session on the provider the README leads with.

## 14. The cap was losing series, silently

Not from the twenty questions. It came out of designing a fix for finding 6 and
is worse than anything the run found, because it was shipped and live.

`fetch_data` sends `lastNObservations` on every request, which is what bounds
the download. ILO applies it by dropping series:

| `lastNObservations` | series returned |
|---|---|
| 1 | 2 |
| 20 | 13 |
| 501 (the default `limit`) | 13 |
| 2001 | 39 |
| not sent | 39 |

So a default `fetch_data` against ILO with no period bound returned 13 of 39
series, with a 200, no truncation note, and nothing else to show for it. BIS,
ECB, IMF and Bundesbank were checked in the same condition and are unaffected.
The existing safety check looks for an empty response, which this is not: the
response has data, it is simply not all of the data.

The check is now a count. The first capped fetch of a provider is compared
against a `detail=nodata` request, which returns the keys without the
observations, and a provider that comes back short loses the cap for the rest
of the process. One extra request per provider.

The verdict is recorded against the cap it was measured at, not as a plain yes,
because the table above is not constant in the cap: a first fetch at
`limit=2000` would otherwise certify ILO as safe and the next one at the
default would lose two thirds of its series again. Asking for more observations
cannot return fewer series, so a verdict holds for any cap at least as large as
the one that produced it.

## What was fixed

Each fix was verified by re-running the question against the live provider. The
second pass is appended to the same log.

| Finding | State | Evidence |
|---|---|---|
| 1. Empty response says nothing | Fixed | Echoes the key and says what to try. 91B to 488B, and the 91B was unusable. |
| 2. Codes without labels | Fixed | Japan's GDP now carries `XDC: Domestic currency`; Singapore's CPI names series `1` as `All Items`; BIS names all 39 areas. |
| 3. Entity search unranked | Mostly | Was the wrong filter, not just the order. See below. |
| 6. No way to find a key that exists | Partly | `detail=nodata` proved out and is used by the count check; no tool exposes it yet. |
| 14. The cap lost series | Fixed | ILO returns 39 of 39 again; the count check catches it and the verdict is recorded per cap. |
| 4. Substring search | Fixed | `"national accounts"` returns 11 flows including `ANEA`, was 1. |
| 7. Undocumented query shapes | Fixed | `+` and the wildcard are in the `fetch_data` description and the instructions. |
| 8. `direct_children` truncates silently | Fixed | Returns `direct_children_total`, and says so when a page was clipped. |

Entity search turned out to be diagnosed wrongly the first time. Ranking was
treated as the problem; the filter was. `filter[fulltext]` matches addresses,
which is why a company near the Spanish city of Santander outranked the bank,
and it did not return `BANCO SANTANDER S.A.` in twenty-five hits at all, so no
amount of local ranking could have reached it. `filter[entity.names]` covers
the legal name and the other names GLEIF holds. It finds トヨタ自動車株式会社
from "Toyota Motor Corporation", which was the case fulltext was chosen for,
and it returns the Spanish parent first for "Banco Santander".

Three things then rank what comes back: how closely the name matches, with
accents folded, since "Nestle" scored nothing against "NESTLÉ S.A."; then
`category`, because a `BRANCH` and a `FUND` are named after the parent and the
Dutch and French branches of Santander are both legally "Banco Santander S.A.";
then `status`, so a dissolved entity does not lead.

Still imperfect on common names. "Nestle" returns an Indian sole proprietor
first, because GLEIF records it under an exact alias of that name, and
"Deutsche Bank" leads with the Italian subsidiary. Nothing in a record marks
the group parent, so the remaining cases need the ownership graph. Both are far
better than before, and neither is right.

Not addressed, and still true:

- **5.** A search returning 108 ILO flows has not narrowed anything.
- **6.** No tool exposes the series that exist, though the mechanism now
  works: `detail=nodata` returns the keys, and Bundesbank rejects
  `serieskeysonly` while accepting it.
- **9.** Vintages crowd out the flow they are vintages of.
- **10.** `fx_period_rate` states less about provenance than `fx_spot`.
- **11.** A provider outage is a raw HTTP string.
- **12.** Aggregates in a codelist are unmarked.
- **13.** BIS prints to stdout mid-call, and the claim that the SDK diverts it
  is still untested.

## Running them again

```bash
uv run python - <<'PY'
import sys; sys.path.insert(0, "evals")
from harness import q, call, note
q(1, "...")
call("find_dataflows", provider="BIS", search="policy rate")
PY
```

`call` goes through `call_tool`, so a question that cannot be answered through
the published tools has not been answered. Everything is appended to
`log/qNN.jsonl`; nothing is overwritten, so a re-run adds a second pass rather
than replacing the first.
