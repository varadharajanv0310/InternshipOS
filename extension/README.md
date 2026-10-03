# InternshipOS browser extension

Load the extension folder as an unpacked Chrome/Edge extension. In the hosted workspace Settings, create a pairing token, then enter https://internshipos.vercel.app/api and the token in the extension Connect tab. The workspace origin permission is requested when you connect. Sensitive/contact question answers stay in local browser storage; passwords, cookies and OTPs are not copied to the server.

## Approved queue

1. Review your profile, project facts and an approved resume version in the workspace.
2. Review the employer identity and official website-to-board association in Companies. Source candidates are not automatically trusted.
3. Prepare an in-scope role, select its exact resume version, review eligibility, then approve its pack in Applications.
4. Enable selected Greenhouse/Lever/Ashby forms and set the daily attempt limit in Settings. Submission remains off until you do this.
5. Save accurate local contact facts and exact question/answer pairs in the extension. Review the batch consent checkbox, then choose Run approved queue and grant supported provider permissions. This snapshots your local facts for that run.
6. Keep the browser open. The queue processes one approved job at a time, saves only confirmed receipts and pauses when a page, unknown answer, conflicting prefilled fact, required widget, resume upload, CAPTCHA or receipt needs attention. Pause queue stops subsequent work; it cannot undo a submission already underway.

The queue does not retry uncertain attempts. Check the employer confirmation and use Check submission receipt with the original application/lease before starting again. Restart recovery also stops interrupted attempts. Browser permissions and real employer forms have not been validated by submitting personal applications during development. The hosted website collects jobs while the browser is closed; application execution requires the paired open browser.

Individual attended filling remains available. Existing fields are preserved for manual review; strict queue execution additionally rejects conflicting prefilled answers. Complex forms, unsupported providers, account challenges and multi-step flows can require manual completion. A successful fill is not an application receipt.

Implementation uses persisted state and alarms rather than assuming a browser service worker stays alive: [Chrome service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).
