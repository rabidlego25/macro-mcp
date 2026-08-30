# Strategy

Working thesis for turning `macro-mcp` into a venture-backable company, written
to be argued with rather than pitched from. Claims that need external
verification are marked **[verify]**. Where the honest answer is "this might not
work," it says so.

## Thesis in one line

Public macro data is free, fragmented and silently overwritten; the durable
business is not access to it but the **point-in-time record and correctness
layer** that agents need in order to be trusted with it. The point-in-time record
already exists publicly and is unusable — making it usable is the opening.

## Honest starting position

What exists today is a competent MCP server over ~24 working SDMX providers plus
Singapore, Hong Kong, GLEIF and ECB FX. It is roughly a day's engineering of real
value on top of an open-source SDMX library, with unusually good discipline about
failure modes. It has no users, no remote and no packaging.

It is not the company. It is the distribution wedge and the proof that the
founder understands the problem domain. Treating it as the product is the main
strategic error available here.

## The insight the company rests on

> **Corrected 2026-08-10 after testing it.** The first version of this document
> claimed the vintage archive was an unoccupied, unbuyable moat. That was wrong,
> and the evidence is in the research log at the end. The corrected version is
> below and it is weaker, but it also removes the plan's worst structural
> problem.

**Statistical agencies overwrite history in place.** When Eurostat revises 2024
German GDP, the previous value is gone from the API. Point-in-time data therefore
has to be captured as it goes; it cannot be reconstructed afterwards.

That much is true. What is *not* true is that nobody has been capturing it.
DBnomics has been committing raw provider data to ~96 public git repositories
since 2017, several times a day on active ones. That is an international vintage
archive, it is public, and anyone can clone it.

So the moat is not possession of the data. **The moat is that the data is
currently unusable.** It sits as nine years of heterogeneous provider-format
files — SDMX-ML, TSV, bespoke JSON, one shape per provider — in git repos with
no query layer, no harmonization, and no exposure through DBnomics' own API.
Turning that into a queryable point-in-time service is substantial engineering,
and it is the same harmonization work that makes the live product good.

This is a weaker moat than exclusive data. It is an execution and product moat,
replicable by anyone willing to do the same work. It has to be paired with speed,
distribution and the guardrail layer to matter.

**But it removes the plan's worst problem.** A capture-from-today strategy has an
asset worth little at month 18, exactly when a Series A conversation happens.
Bootstrapping from public history means launching with nine years of revisions on
day one. That is the difference between promising a moat and demonstrating one.

**Still worth running your own capture, from now.** DBnomics does not cover
everything (HKMA and SingStat are absent), some repos stall — Eurostat's has been
untouched since January 2026 — and depending on a third party for the core asset
is not a strategy. Bootstrap from theirs; do not rely on theirs.

FRED/ALFRED proves the demand exists — economists have used it for two decades.
It does not, as previously claimed here, prove nobody has done it internationally.

## Problem

Anyone comparing economies across borders hits the same four failures, none of
which raise an error:

1. **Data is fragmented.** No global EDGAR, no shared company key, every provider
   codes countries differently.
2. **History is as-revised, not as-known.** Backtests silently use numbers nobody
   had at the time.
3. **Series look comparable and are not.** Nominal against PPP, EU27 against
   France, X-13 against TRAMO/SEATS, fiscal years that are not calendar years.
4. **Conversion is convention-dependent.** Converting a flow at an end-of-period
   rate is wrong by percent, and nothing flags it.

An analyst learns these over years. An LLM does not know them, and produces
confident, well-formatted, wrong answers. That gap is the product surface.

## Why now

- Agents are entering financial workflows, where a wrong number has consequences
  and "the model said so" is not a defence.
- The incumbents in macro data — Macrobond, Haver, CEIC — are seat-licensed
  desktop products built for humans, not agent-native. **[verify]** their current
  pricing and whether any has shipped an agent interface.
- MCP is becoming a default integration surface, which lowers distribution cost
  for a small team. It is also young and may be superseded; do not build anything
  that only works if MCP wins.
- Storage is cheap enough that a daily full-corpus snapshot is a rounding error.

## Product, in three layers

| Layer | What it is | Role |
|---|---|---|
| **Server** | Open-source MCP server over public providers | Wedge and credibility. Free forever. |
| **Archive** | Daily vintages of every series captured | Moat. Compounds. Paid. |
| **Guardrails** | Comparability checks, FX conventions, provenance | Product. What people pay for. |

The open-source layer is genuine and stays free — it is the distribution channel
and the reason anyone trusts the rest. The archive and guardrails are hosted,
paid, and impossible to replicate from the repo alone.

### What the guardrail layer actually does

Today the caveats live in prose in the server instructions, which a model may or
may not honour. Made mechanical, they become the product:

- refuse or flag a comparison mixing aggregates with their members
- refuse or flag nominal against PPP against constant-price
- require an explicit FX convention, as `fx_period_rate` already does
- return provenance with every number: provider, flow, vintage, retrieval time
- return an audit record: what an agent asked, what it got, from when

The audit record is the enterprise wedge. A regulated user needs to prove which
data a decision was made on. Nobody in this category offers that for agents.

## Moat, honestly rated

| Candidate | Real? | Notes |
|---|---|---|
| Exclusive vintage data | **No** | Publicly archived since 2017. Anyone can clone it. |
| Usable vintage data | Medium | Nine years of heterogeneous files with no query layer. Hard work, not secret work. |
| Harmonization/mapping layer | Medium | Real effort, accumulates, replicable with money. Compounds with the archive. |
| Provider quirk knowledge | Weak | ~200 lines of tables. A week to re-derive. |
| Open-source distribution | Medium | Mindshare and trust, not defensibility. |
| Brand as "the correct one" | Medium | Only if the evals are public and it actually is. |
| The code itself | **No** | Thin layer over open-source libraries. |

No single row here is strong. The honest read is that defensibility comes from
stacking a medium data-usability moat on a medium harmonization moat and moving
faster than a project with no commercial motive. That is a real but ordinary
startup position, and it should be described that way rather than dressed up.

## Market

**[verify all of this before it goes in a deck.]** The category — Macrobond,
Haver Analytics, CEIC, plus macro modules inside Bloomberg and LSEG — appears to
support several hundred million in annual revenue, at seat prices in the tens of
thousands. Macrobond was reported to have taken majority investment from
Francisco Partners at a valuation around the high hundreds of millions
**[verify]**.

That sizing supports a good venture outcome, not an obvious fund-returner, *if
the buyer set stays the same*. The bet worth making is that agents expand the
buyer set: from a few tens of thousands of professional macro seats to every
analyst, corporate strategy team and AI product that needs a defensible number.

**Beachhead, not market.** Macro is the entry point because it is fragmented,
painful, and free of licensing cost. The expansion is the same trust layer over
company fundamentals, filings and micro data. Say this explicitly to investors;
"macro data" alone will read as too small, and they will be right.

## Business model

1. **Free** — open-source MCP server, live data, no archive. Distribution.
2. **Pro** — hosted API: vintages, guardrails, provenance. Usage or seat priced.
3. **Enterprise** — audit trail, SLA, private deployment, custom providers.

Usage-based pricing on the archive fits agent consumption better than seats, and
undercuts the incumbent model rather than imitating it.

## Go to market

Lead with one visceral demonstration, not with coverage. Coverage is not a value
proposition and "31 providers" was inflated even as a fact.

- **Demo 1, the revision.** Japan's 2024 nominal GDP reads ¥634.75tn today and
  ¥634.23tn in the April 2026 vintage. Every backtest run before that used
  numbers nobody had. This is already demonstrable in the repo.
- **Demo 2, the guardrail.** An agent confidently sums EU27 and France. Then the
  same agent, with the layer, refuses and explains.

Sequence: publish the evals openly → open-source server for credibility → inbound
from the demos → hosted archive for the people who felt the pain.

Selling to hedge funds is slow, high-touch, and they may simply build it. AI
companies and fintechs embedding macro data are faster to close at lower ACV and
are the better first cohort.

## Competition

- **Macrobond, Haver, CEIC** — deep harmonization and long vintage history.
  Expensive, human-first, slow-moving. **[verify]** their agent posture.
- **Bloomberg, LSEG, FactSet** — broader and richer; macro is one module. Will
  not move quickly on agent-native interfaces, but can.
- **FRED/ALFRED** — free, excellent, US-only. The proof of demand and the model
  to generalize internationally.
- **DBnomics** — the most important competitor, and previously underrated here.
  Public, free, ~96 providers, and quietly the largest international vintage
  archive that exists (see research log). Backed by CEPREMAP, French public
  research **[verify]**, which suggests no commercial motive — but that cuts both
  ways. Either they will not productize this and the opening is real, or nobody
  has asked them to because the demand is not there. **Resolve this by talking to
  users, not by reasoning about it.** They are also the natural acquirer,
  partner, or the party who kills the idea by shipping a vintage API first.
- **Trading Economics** — closest commercial cheap analogue. **[verify]**.
- **The providers themselves** — could publish vintages at any time. IMF already
  does, partially. This is a real and underrated threat.

## Plan

**Now, before anything else (days)**
- ~~Fix the truncation bug — silent data loss in the core response path.~~
  **Done 2026-08-20.** The budget is now shared across series and hoisting is
  decided before truncation, so a clipped response can no longer read as a
  complete one.
- ~~Per-host rate limiting and backoff.~~ **Done 2026-08-20.** One transport
  adapter now carries every request: a concurrency cap per host, HKMA paced at
  the 4/s that stopped its 502s, transient statuses retried with jittered
  backoff, and `Retry-After` held against the whole host rather than the one
  request that drew it. It bounds a single process, so it does not solve the
  shared User-Agent — that needs the hosted deployment, where the footprint is
  measurable and attributable.
- ~~Make `limit` bound the download, not just the response.~~ **Done
  2026-08-30.** `lastNObservations` is sent to every SDMX provider, so a
  three-observation question costs 10KB of BIS rather than 314KB, and 3KB of
  ECB rather than 1.4MB. It costs the exact `total`: once the cap binds, the
  response reports a floor, because counting the rest means downloading it. It
  buys nothing on an already-narrow query, and nothing at all on the structure
  metadata, which is the larger half of a cold fetch — 3.5MB per IMF DSD
  against 4KB of observations. Bounding **that** is the next one.
- **Start the daily snapshot** for providers DBnomics does not cover, and where
  its repos have stalled. Cheap, boring, and the clock does not restart.
- **Clone the DBnomics history** before doing anything else with it — it is a
  third party's infrastructure and could go private, be pruned, or stop. Cloning
  is free and reversible; losing it is not. Resolve the licence question in
  parallel, but do not let that block the clone of public data.

**Weeks 1–6**
- Evals: 20 real questions, agent-run, every dead end logged and fixed. Publish
  them. This is the gate; nothing ships to strangers before it passes.
- Package and publish so install is one line.
- Verify data licensing per provider (see Risks). Non-negotiable before hosting.
- Add FRED/ALFRED. Drop the keyless rule; keep keyless as the default path.

**Months 2–6**
- Guardrails mechanical rather than prose.
- Hosted archive API with provenance on every value.
- First 10 design partners, weighted to AI/fintech rather than funds.

**Months 6–18**
- Audit trail and enterprise controls.
- Broaden coverage where evals show real demand, not by provider count.
- By month 18 the archive is the pitch: 18 months of vintages nobody else has.

## Risks, and what would kill it

- **It is a feature, not a company.** An incumbent or a model provider ships
  macro connectors and the wedge closes. Mitigation: the archive, which they
  cannot backfill either.
- **Data licensing, now the largest unresolved risk.** The business redistributes
  others' data. IMF, World Bank and Eurostat are generally permissive with
  attribution; some national offices are not, and a stored vintage archive is
  legally different from proxying a live request. The DBnomics source repos carry
  **no declared licence** and the project's own legal page returns a 400, so
  reuse rights there are genuinely unclear and cannot be assumed. **Resolve
  before hosting anything, per provider and for DBnomics separately.**
- **Someone already keeps vintages internationally — confirmed, they do.** This
  was the cheapest question in the first draft and it came back against the
  thesis. The idea survives in weakened form (see the corrected insight), but
  anyone diligencing this will find DBnomics within an hour. Lead with it.
- **DBnomics productizes vintages themselves.** They have the data, nine years of
  head start, and public-research funding. The counter is speed, agent-native
  design and a guardrail layer they show no sign of wanting to build.
- **Not venture-scale.** Plausibly a very good $3–8M ARR business, which is a
  fine life and a poor venture outcome. Taking money forecloses that path.
- **Maintenance drag.** Hard-coded catalogues, corrected base URLs and a snapshot
  capability table all rot. ~~Weekly CI on the live suite turns debt into a
  notification.~~ **Done 2026-08-20**, but it needed the live suite split
  first: it pinned values that revise, including one read from the current IMF
  flow, so a schedule would have gone red because a provider did its job. Drift
  now fails the build; a revision reports and cannot.
- **Models get good enough to just use the raw APIs.** Real, and it argues for
  investing in the archive and guardrails rather than the access layer, which is
  what commoditizes first.
- **Solo founder, no domain credibility.** Public evals and open source are the
  cheapest way to buy both.

## Why this might not be venture-scale

Worth stating plainly, since the rest of the document argues the other way.

The category is real but not obviously large. The incumbents are decades old and
their customers are sticky and few. The wedge is free software that anyone can
fork. The moat takes years to become meaningful, which is exactly the shape
venture timelines handle badly — an asset that is worth little at month 18, when
the Series A conversation happens.

The honest version of the pitch is: *this is a slow-compounding data asset with a
software business attached, in a category that supports hundreds of millions
rather than billions, and its defensibility arrives late.* Some investors want
precisely that. Most do not. Pick accordingly, and do not disguise the shape of
it — it will surface in diligence, and it is more persuasive said first.

## Open questions to resolve before raising

1. ~~Does anyone already keep international vintages?~~ **Answered: yes, DBnomics
   does. See research log.**
2. What do provider licences permit for storage and redistribution, per provider —
   and what, if anything, do the DBnomics repos permit? Now the top risk.
3. Do the evals pass? Can an agent actually answer 20 real questions end to end?
4. Why has DBnomics not productized nine years of vintages — no commercial motive,
   or no demand? Distinguishing these two is the most valuable thing anyone can
   learn about this market, and it can only be learned from users.
5. Who felt this pain enough to pay — and is that a list of 200 firms or 20,000?
6. Adoption or revenue? It changes what gets built first, and the answer should
   be decided rather than deferred.

## Research log

Findings recorded with method and date so they can be re-run and challenged.
Everything below was measured, not recalled.

**2026-08-10 — Does anyone keep international vintages? Yes.**

- DBnomics stores raw provider data in ~96 public git repositories at
  `git.nomics.world/dbnomics-source-data`, oldest created 2017-04-12.
- Commits are titled "Download data from provider" — these are periodic snapshots
  of source-format data, i.e. vintages.
- Cadence on an active repo (INSEE, project 45): 100 commits across 26 distinct
  days, 2026-07-16 to 2026-08-10. Roughly four a day, daily.
- 52 of 96 repos show activity in 2026; 12 last active in 2025, the rest older.
  Eurostat's repo (project 197) has been untouched since 2026-01-20, so coverage
  is uneven and cannot be assumed live.
- DBnomics' own API exposes no vintage or revision fields. WEO appears as dated
  editions (`WEO:2008-04` onward) only because IMF versions that publication
  itself — not because the API surfaces vintages generally.
- No LICENSE file in the source repos; `db.nomics.world/legal` returns 400.

*Conclusion:* the data exists publicly and is not usable as data. That is the
opening, and it is a narrower one than this document originally claimed.

**Still to run**

- Clone one provider's full history and measure: how many series were revised,
  how often, and by how much. This is the number that tells you whether the
  archive is worth anything to a customer, and it is directly measurable.
- The same for a provider DBnomics does not cover, to size the gap.
