# Eval questions

Twenty questions written before any of them was run, so the set is not tuned to
what happens to work. Each is a question somebody would actually ask, and each
also stresses something the server claims to handle. The claim is in the second
line; a question that only exercises the happy path is not worth a run.

The rule for answering: only the eleven tools, in the order discovery
prescribes. No reaching past them into the modules, and no using knowledge of a
provider's codes that `search_codes` would have had to supply.

## Rates and currency

1. **What was the Bank of Japan's policy rate at the end of 2024, and how did
   it compare with the ECB's?**
   Two countries from one flow, and the geo codes differ per provider.

2. **How much did the yen move against the euro over 2024?**
   Whether the response says these are a fixing rather than a traded rate.

3. **A Japanese subsidiary reported 8.4bn yen of revenue in 2024. What is that
   in euros?**
   A flow converts at the period average. Picking end-of-period is silent.

4. **What is the current EUR/USD rate, and is it a rate anyone traded?**
   Provenance: every ECB rate is quoted against the euro.

## Levels, units and scale

5. **What was Japan's nominal GDP in 2024?**
   The multiplier. A bare number here is off by a factor of a thousand or more.

6. **Was Italian inflation higher or lower than German inflation in 2024?**
   Two national sources, or one comparable one. Index versus percent.

7. **What was euro area unemployment in mid-2025?**
   Seasonal adjustment, and whether the response says which it is.

8. **What was Germany's 10-year government bond yield most recently?**
   Bundesbank is an adapter rather than the SDMX spine.

## Country codes and aggregates

9. **What was France's GDP in 2024, and what share of the EU is that?**
   EU27 and France live in the same codelist. Summing both double-counts.

10. **Which Asian economies does the BIS publish a policy rate for?**
    Reading a codelist rather than guessing country codes.

## Point in time

11. **Has the IMF revised Japan's 2024 GDP since it first published it?**
    The one place this server can answer as-known rather than as-revised.

12. **What did the IMF say Japan's 2024 GDP was in early 2026?**
    Vintage coverage varies as well as values.

## Entities

13. **What is Toyota's LEI?**
    A legal name in a native script, with the Latin one as an alias.

14. **Does Toyota have registered subsidiaries outside Japan?**
    The ownership graph, and country on every hit.

15. **Find Banco Santander and confirm which country it is registered in.**
    A name that matches many entities in several jurisdictions.

## Adapters that are not the spine

16. **What was the Hong Kong overnight HIBOR at the end of 2024?**
    HKMA ignores a date range unless the period column is named.

17. **What was Singapore's CPI in 2024?**
    SingStat writes periods as `2024 Jan`, which join against nothing raw.

## Discovery under ambiguity

18. **Which providers here can tell me about Indian inflation?**
    Whether `list_providers` plus search is enough to answer a coverage question.

19. **I want Italian agricultural output.**
    ISTAT names the flow `Coltivazioni`. Search is supposed to cross that.

20. **What is the US unemployment rate?**
    Several providers carry it. Whether the agent can choose one and say why.
