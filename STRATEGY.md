# Strategy

Working thesis for turning `macro-mcp` into a venture-backable company, written
to be argued with rather than pitched from. Claims that need external
verification are marked **[verify]**. Where the honest answer is "this might not
work," it says so.

## Thesis in one line

Public macro data is free, fragmented and silently overwritten; the durable
business is not access to it but the **point-in-time record and correctness
layer** that agents need in order to be trusted with it.

## Honest starting position

What exists today is a competent MCP server over ~24 working SDMX providers plus
Singapore, Hong Kong, GLEIF and ECB FX. It is roughly a day's engineering of real
value on top of an open-source SDMX library, with unusually good discipline about
failure modes. It has no users, no remote, no packaging, and one known
correctness bug at time of writing.

It is not the company. It is the distribution wedge and the proof that the
founder understands the problem domain. Treating it as the product is the main
strategic error available here.

## The insight the company rests on

**Statistical agencies overwrite history in place, and the past is not
recoverable.** When Eurostat revises 2024 German GDP, the previous value is gone
from the API. There is no way to buy it back later, and no competitor can
retroactively acquire it.

So a system that snapshots public statistical data daily accrues an asset that:

- costs almost nothing to build (storage, plus a scheduler)
- compounds automatically with time, with no additional insight or effort
- cannot be replicated by a better-funded competitor entering in year three
- gets more valuable exactly as agent-driven backtesting grows

This is the only defensible thing in the vicinity. Everything else here — the
adapters, the compaction, the quirk tables — is re-derivable by a competent
engineer in a week, and increasingly by a model in an hour.

**The single most important consequence: start capturing now.** Before the
product is designed, before the company exists, before anyone is hired. Every
day of delay is a day of archive that can never be created. This is cheap enough
to do as a cron job and irreversible enough to be the difference between a
defensible company and a wrapper.

FRED/ALFRED proves the demand exists — economists have used it for two decades —
and proves nobody has done it outside the US.

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
| Vintage archive | **Yes** | Compounds daily, cannot be bought retroactively. The only strong one. |
| Provider quirk knowledge | Weak | ~200 lines of tables. A week of work to re-derive. |
| Harmonization/mapping layer | Medium | Real effort, accumulates, but replicable with money. |
| Open-source distribution | Medium | Mindshare and trust, not defensibility. |
| Brand as "the correct one" | Medium | Only if the evals are public and it actually is. |
| The code itself | **No** | Thin layer over open-source libraries. |

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
- **Trading Economics, DBnomics** — closest free/cheap analogues. **[verify]**
  whether DBnomics keeps vintages; if it does, that materially weakens the moat
  and must be known before raising.
- **The providers themselves** — could publish vintages at any time. IMF already
  does, partially. This is a real and underrated threat.

## Plan

**Now, before anything else (days)**
- Fix the truncation bug — silent data loss in the core response path.
- Per-host rate limiting and backoff. A shared User-Agent across many users is a
  single point of failure; one provider blocking it breaks everyone at once.
- **Start the daily snapshot.** Cheap, boring, and the clock does not restart.

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
- **Data licensing.** The business redistributes others' data. IMF, World Bank
  and Eurostat are generally permissive with attribution; some national offices
  are not, and a stored vintage archive is legally different from proxying a live
  request. **This is a genuine diligence item and could invalidate the moat for
  specific providers. Resolve it before hosting anything.**
- **Someone already keeps vintages internationally.** Would substantially
  devalue the core idea. **[verify]** first, cheaply.
- **Not venture-scale.** Plausibly a very good $3–8M ARR business, which is a
  fine life and a poor venture outcome. Taking money forecloses that path.
- **Maintenance drag.** Hard-coded catalogues, corrected base URLs and a snapshot
  capability table all rot. Weekly CI on the live suite turns debt into a
  notification.
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

1. Does DBnomics, or anyone, already keep international vintages? *(Cheapest to
   check, largest impact on the thesis.)*
2. What do provider licences permit for storage and redistribution, per provider?
3. Do the evals pass? Can an agent actually answer 20 real questions end to end?
4. Who felt this pain enough to pay — and is that a list of 200 firms or 20,000?
5. Adoption or revenue? It changes what gets built first, and the answer should
   be decided rather than deferred.
