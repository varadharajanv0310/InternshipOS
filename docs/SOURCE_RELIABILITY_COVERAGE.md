# Source reliability: inventory and detail coverage

## Diagnosis, 6 October 2026

Source health currently conflates two independent facts: whether every listing was enumerated and whether every full job description was fetched. Several adapters stop enumerating when the detail budget is exhausted. Several others enumerate all jobs, but restart description requests at the first row on every run. Increasing the budget alone cannot fix the resulting starvation.

Confirmed code-level problems:

- SmartRecruiters, Workable, BambooHR, Breezy and Pinpoint have no continuing detail cursor. Roles after the first bounded detail batch can remain permanently unenriched.
- Pinpoint recognizes a next-page link but never follows it.
- Lever and Amazon have no listing continuation after the page budget.
- Workday, Oracle and Eightfold use description-budget progress as their listing offset. A bounded description pass prevents discovering later listing rows until a subsequent run.
- Workday totals at or above its 2,000-result cap must remain incomplete; pagination is not proof that a capped query represents the whole board.
- A continuation, query or discovery scrape must not be used as a full-board closure proof.

## Implemented changes

Workday, Oracle, Eightfold, SmartRecruiters, Workable, BambooHR, Breezy and Pinpoint now enumerate bounded listing inventory before choosing a rotating batch of details. Inventory completion and detail completion are recorded separately. A persisted detail cursor lets later runs enrich different roles without repeatedly spending the budget on the first jobs. A valid response without the required full description is recorded as unavailable, rather than counted as a successful description refresh.

In target-only worker runs, technical internship candidates take priority on every run. Narrowly generic India titles such as “Intern” receive a description request so the classifier can determine the technical role. The final location and role retention policy is unchanged. Historical foreign appearances remain in the enumerated inventory; their descriptions use spare requests and an independent `retained_detail_cursor`, so old US listings cannot consume the new India candidate budget.

Pinpoint follows validated same-origin next-page links, rejecting repeated pages and cross-origin links. Workday, Eightfold, Lever and Amazon now expose a separate `listing_cursor` when their listing page budget ends. A resumed segment never becomes a full inventory absence proof. Workday's 2,000-result cap and a total that changes during pagination remain explicit incomplete outcomes. Negative, boolean and otherwise malformed provider counts cannot become successful empty inventories.

Oversized Greenhouse description responses fall back to the lightweight public listing endpoint. Every listing identity remains observable; descriptions are fetched through the bounded, rotating candidate pass. The normal transport limit is preserved. This fallback does not claim that access-challenged pages were repaired.

Declared public search feeds support GET and POST requests, literal JSON or URL-encoded form bodies, explicitly declared query parameters and headers, and bounded pagination. The field grammar supports simple properties, array traversal, fallback paths and structured concatenation/maps without evaluating expressions. JSON objects encoded inside form values can contain the pagination parameter. GraphQL mutations/subscriptions are rejected before a request. A declared summary-only feed keeps its original snippet as raw evidence without presenting it as a full job description; unknown pagination can be explicitly flagged as unproven inventory.

Internshala's current card title markup is supported, hiring badges are excluded from employer names, its existing work-from-home India context is normalized, and observed same-origin next-page links are followed within the listing budget. Continuations retain discovery scope. A stale cursor resets for a new zero-offset verification pass rather than declaring the continued segment complete.

## Validation

- Focused regression run: **86 passed** on 6 October 2026. This includes 45 existing ingestion tests, 35 new coverage cases and six separately authored Internshala layout cases.
- The coverage tests verify listing-before-details behavior, bounded requests, detail rotation, independent retained-history progress, target preference, multi-page enumeration, shrink handling, changing/malformed totals, page continuation, repeated/cross-origin next links, the Greenhouse size fallback, configured JSON/form pagination, empty-array schema validation, rejected GraphQL writes and non-executing field paths.
- Independently fetched, saved Internshala HTML previously returned zero parsed jobs. The repaired parser recovers **52 of 52 cards** on the computer-science page and **11 of 11 cards** on the Chennai software-development page. Existing policy retains 14 and seven candidate roles respectively; parsing every card does not make every card relevant.
- Raw live HTML and probe metadata are stored privately under `data/private/source-reliability/`; the minimal markup fixture contains no credentials. Broader live endpoint outcomes, database changes and cloud execution are handled by the parent task and must be assessed separately from these mock tests.

## Remaining limits

Numeric cursors distribute bounded work; they are not stable inventory snapshots across multiple runs. Changed ordering or board growth can require another complete scan. Large or capped global boards still need scoped partitions to prove all relevant listings were enumerated. Candidate filtering deliberately does not assume worldwide remote roles are eligible for India. An explicit configured feed can remain partial when it has unknown pagination or only preview descriptions. The source registry must supply verified current endpoints, accurate field mappings and the correct pagination parameter; adapter support alone cannot make a dead, challenged or misconfigured endpoint healthy.

## Files changed by this subtask

- `backend/internshipos/ingestion/adapters.py`
- `backend/tests/test_coverage_reliability.py`
- One existing Workday-budget regression in `backend/tests/test_ingestion.py`, updated with parent authorization to assert the stronger list-first inventory contract.
- This document.

The parent task owns collector metadata serialization, checkpoint persistence, health labels, scheduling, deployed configuration and live verification. No provider credentials, model choices or automatic-application behavior were changed by this subtask.
