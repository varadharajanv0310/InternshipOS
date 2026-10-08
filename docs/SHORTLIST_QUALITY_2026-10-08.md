# Shortlist quality — 8 October 2026

This repair keeps source history and application records intact. Guarded hosted reconciliation was applied after a saved dry-run and before-image: 273 historical description dates recovered, seven proven URL aliases added and seven Workday identity discrepancies flagged. No model changes or automatic submissions were performed.

## Implementation checklist

- [x] Explain degree, graduation, availability and explicitly required skill checks using employer text and confirmed profile facts.
- [x] Correct the UI mapping that currently displays both `probably eligible` and `probably ineligible` as “Unclear”.
- [x] Keep separate listing and full-description clocks; stale or missing evidence requires review before recommendation/preparation.
- [x] Persist owner exclusions for individual roles and companies with restoration, shared by the feed, dashboard, analytics and preparation.
- [x] Associate proven mirrored requisitions without deleting opportunities or losing sources/history; conflicting requisitions remain distinct.
- [x] Provide dry-run reconciliation and flag historical Workday location-valued IDs for review.
- [x] Add meaningful regression checks and validate the frontend build.

Evidence constraints: skill mentions alone are not mandatory requirements; preferred qualifications are not hard exclusions. Missing applicant facts, unknown description age and ambiguous prose remain unknown. An upstream partial collection never proves a role closed.

## Resulting behavior

Eligibility retains the conservative labels “Likely eligible”, “Likely ineligible” and “Unclear”. Each check retains the employer wording, required/preferred distinction, outcome and reason. Degree levels, explicitly named subjects, discrete graduation cohorts, CGPA on matching scales, explicitly required skills, confirmed enrollment/completion and published availability are checked. Missing skill mentions in the profile remain unknown rather than proof of inability. Ambiguous/unparsed restrictions require manual review; passing extracted checks is not a guarantee of complete employer eligibility.

The profile editor accepts confirmed enrollment/completion and availability in weeks as well as months. Week requirements are not silently converted to months. Unknown eligibility is explicitly labelled “Review eligibility before applying”, even when fresh evidence makes the role worth reviewing.

Listing observations and full-description observations have separate clocks. Listing evidence older than 48 hours, descriptions older than seven days, unknown detail age, missing application URLs, passed deadlines or historical identity concerns require review before creating a new Ready application or approving/claiming a submission lease. Sparse listing refreshes retain the old description clock. Unchanged real description reads refresh it; unverified mirrors cannot refresh an authoritative cached description. Stale is a review state, not an eligibility decision or a closure inference. Disabled monitors retain real recent observations, which age normally; superseded routes cannot establish current liveness.

Owner exclusions are stored in the existing settings table under `shortlist_exclusions`, separately for opportunity IDs and company IDs. The opportunities screen offers “Exclude this role”, “Exclude company”, and an “Excluded roles & companies” restoration list. Company restoration keeps individual role exclusions. Visible opportunity metrics and dashboard recommendations use the same choices, while historical applications, PDFs, receipts and raw collected-record counts remain accessible. Preparation packs include `readiness` and `ready_to_prepare`; existing approval/receipt records are not rewritten when a fresh check blocks further action.

The “Recheck posting” action queues only an opportunity ID. The worker resolves verified public appearance IDs and URLs server-side, fetches the exact role, and preserves full-board coverage/cursors. The UI polls the owner-protected job status and waits for actual observations; queueing never changes freshness. Unsupported/backoff/identity-review cases retain actionable reasons.

Company priority remains the default ranking, with the existing Bengaluru/Chennai/remote India/India-unspecified policy. Fit and role value remain separate from company priority, and no compensation facts or hiring probabilities are invented. Automatic submission settings are unchanged and remain off in production.

## Safe mirror identity and historical review

An exact canonical URL requires the same actual observed employer and title with no conflicting requisition. Cross-board requisition identity requires verified observations and an explicit provider requisition field or a labelled requisition ID. Bare generic numeric job IDs are insufficient. Distinct postings within one board remain separate when their only match is a requisition; conflicting requisitions cannot be bridged through a third record lacking an ID. Parent-company identity does not override distinct observed subsidiaries.

Reconciliation creates reversible visibility aliases using `duplicate_of` and `mirror_ids`. It does not delete opportunities, move application/task/resume references, move source rows, or discard snapshots, evaluations and identity history. The primary role presents the full source trail; analytics count it once while preserving source appearances. Historical source IDs that disagree with an observed Workday posting path are flagged for review, retained verbatim and withheld from recommendations. Reversed aliases are not silently recreated by a later reconciliation.

## Backfill and reversal interface

No shortlist schema migration is required. Existing JSON fields, evidence rows and identity-decision history are used. Hosted reconciliation examined 494 target candidates and retained all opportunity, source and application references. Private before-images and per-record outcomes allow review and reversal.

```python
from internshipos import service

# Pass the useful shortlist IDs obtained with the established location policy.
# Pages are bounded; related employer/title identity candidates are included
# automatically, even if the primary role is outside the requested page.
preview = service.reconcile_shortlist_quality(
    db, opportunity_ids=shortlist_ids, limit=100, offset=0, apply=False
)
# Inspect mirror_groups and identity_review before applying this concrete batch.
result = service.reconcile_shortlist_quality(
    db, opportunity_ids=shortlist_ids, limit=100, offset=0, apply=True
)
db.commit()

# Restore a reviewed mirror without deleting its evidence or history.
service.reverse_shortlist_alias(db, mirror_id)
db.commit()

# Restore a role/company owner's choice independently.
service.set_shortlist_exclusion(db, {
    "kind": "company", "id": company_id, "excluded": False
})
```

`apply=False` makes no changes. In a dry run, `evaluation_candidates`, `mirror_groups`, `aliases_added` and `description_clocks_recovered` describe proposed work; `evaluated` stays zero. Applied batches update evaluations only for the requested page, while a proven mirror association can update a related primary role. Historical clocks are recovered from the actual matching promoted-description snapshot, never reset to the time of migration. Snapshot/evidence/evaluation reads are batched; a regression check verifies a one-role page still finds an outside-page primary without per-record reads.

## Validation and remaining limits

The targeted shortlist/domain/workflow regression suite passed 91 checks before the final queue-history regression was added. The full parent-run backend suite then passed 353 checks with four PostgreSQL-only skips; frontend passed 14 checks, extension passed 16, and the production frontend build passed. The deployment owner will record the final aggregate validation and hosted reconciliation outcomes separately.

Coverage includes preferred qualifications, absent profile facts, degree conflict, explicit cohort ranges versus discrete years, missing required skills, sparse and unchanged description clocks, lower-authority mirrors, exclusion/restoration consistency, trusted versus unsupported requisitions, retained application/source history, reversible aliases, conflicting-ID bridges, historical Workday identity review, bounded candidate expansion, and stale approvals retaining their history.

The rules interpreter is deliberately limited: unusual prose, legal/work-authorization restrictions and unknown availability remain a review task. The engine does not claim all internships are found or that every employer restriction was parsed. Related listings with insufficient employer/requisition proof remain separate, and historical identity flags require review rather than automatic destructive repair.

Changed implementation files: `backend/internshipos/domain.py`, `service.py`, `serialize.py`, `api.py`, new `shortlist.py`, `application_queue.py`, `resumes.py`; frontend `Opportunities.tsx`, `presentation.ts`, and only the ProfileSettings controls in `Settings.tsx`; regression files `backend/tests/test_shortlist_quality.py` and `frontend/tests/presentation.test.mjs`. Worker refresh implementation is owned by the collection-capacity task.
