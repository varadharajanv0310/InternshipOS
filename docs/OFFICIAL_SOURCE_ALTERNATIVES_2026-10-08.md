# Official source alternatives — 8 October 2026

This read-only audit followed bounded official employer career-page chains for 33 obsolete, restricted or previously unresolvable source routes. Raw pages, exact links and checkpointed per-employer outcomes are saved privately under `data/private/source-reliability/alternatives-2026-10-08/`. A newly found route remains a candidate until its actual inventory succeeds; a parent's board cannot silently replace a subsidiary's distinct hiring scope.

## Concrete employer-linked routes

| Employer | Official evidence | Observed route and next action |
| --- | --- | --- |
| Unity Technologies | [Open positions](https://unity.com/careers/positions) | Links `unitytech.wd1.myworkdayjobs.com/Unity`; verify and replace the obsolete `unity3d` Greenhouse route. |
| PTC | [Careers](https://www.ptc.com/en/careers) | Links `ptc.wd1.myworkdayjobs.com/PTC`; establish the exact site/alias relationship to the existing working Workday source before retiring Eightfold. |
| Northern Trust | [Careers](https://www.northerntrust.com/asia-pac/about-us/careers) | Links the existing working `ntrs.wd1.myworkdayjobs.com/northerntrust`; bind the obsolete Talentnet alias with preserved history. |
| BNY | [Work with us](https://www.bny.com/corporate/global/en/about-us/careers/work-with-us.html) | Links Oracle site `BNY-Careers`; verify that site's actual inventory rather than assuming the existing `CX_1` scope is equivalent. |
| CleverTap | [Careers](https://clevertap.com/careers/) | Links [Kula](https://careers.kula.ai/clevertap); implement the public listing/detail contract and verify it. |
| MoEngage | [Careers](https://www.moengage.com/careers/) | Links [Trakstar Hire](https://moengage.hire.trakstar.com/); implement its public listing/detail contract. |
| Zeta | [Work with us](https://www.zeta.tech/in/careers/work-with-us) | Its explicitly included public `work-with-us.js` declares `api.lever.co/v0/postings/zeta?group=team&mode=json`; verify the corresponding Lever inventory. |
| Dell Technologies | [Current public job search](https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/jobs) | Current official domain hosts Oracle job search; verify its custom-host contract as a replacement for the rejecting Workday route. |
| Google DeepMind | [Careers](https://deepmind.google/careers/) | Current open-roles link points to Google Careers with `company=DeepMind`, replacing the old `/about/careers/` route; keep the employer filter and query scope. |
| Glance | [Careers](https://glance.com/careers) | Explicit Greenhouse job links confirm the existing board. Its previously failing route already succeeded in the fresh baseline; no additional repair is claimed. |

## Scope and access cautions

- Coinbase's parent board is already working. That alone does not establish that the retired `cdpjobs` subsidiary board has equivalent coverage.
- American Express's footer links an Oracle domain under **Colleagues**. That is an employee-portal reference, not proof of a public recruitment board; it must not be promoted from this evidence alone.
- NIO's current public careers page exposes US/European positions. It does not establish India-accessible internships, and no India availability is inferred.
- Several official pages still reject ordinary public requests. Access restrictions remain visible; this audit uses no account session, proxy or challenge solving.

## LinkedIn timeout experiment

JobSpy's public listing/detail source was inspected locally. Its previous configuration fetched descriptions for every returned role before handing any results back to the parent worker; serial detail requests could consume the subprocess's 75-second limit and lose usable listings.

The new public reader uses the same ordinary unauthenticated guest routes, enumerates the bounded search window first, then enriches relevant regional candidates with the shared rotating detail budget. Numeric URL/URN identities, primary title and employer, final URL and available document canonical identity are checked. Search results remain discovery scope and cannot establish company-wide absence. Public requests share a conservative pace, and detail requests stop after an access restriction rather than hammering the service.

Initial observed contract: ten listing cards and a correctly bound full description in two HTTP200 requests. Two 30-result searches collected seven relevant descriptions each but hit a detail HTTP429 and the eight-detail test budget; both remained explicitly partial. Eighteen focused identity, schema, pagination, partial-result and restriction tests pass. Final deployed checks will be recorded in the main improvement validation.
