# InternshipOS browser extension

In Chrome/Edge, open the extensions page, enable Developer mode, choose **Load unpacked**, and select this `extension` folder. In InternshipOS Settings, create a pairing token and paste it into the extension's Connect tab. Permission is requested only for your workspace URL; page access comes from your click.

Save a role reads public JobPosting metadata or visible page content, lets you review the employer/title, and preserves the page as provenance. Prepared applications come from your own workspace. Contact/sensitive question answers live only in `chrome.storage.local`; cookies, passwords and OTPs are never copied to the server.

Attended filling supports semantic native fields, exact-answer selects, resume PDF files and repeat visits to successive pages. Existing answers are preserved. Complex dynamic or ambiguous required widgets are flagged for manual review. Greenhouse, Lever and Ashby have explicit provider boundaries; other pages can use conservative generic filling.

Automatic submission is **off by default**. It additionally requires workspace authorization for that provider, the user's per-application checkbox, an approved resume, no missing required fields and no detected CAPTCHA. A successful form fill is never recorded as Applied. A recognized same-provider confirmation receipt, or a separate user confirmation in the app, is required. Receipt text/URL and exact resume version are preserved. Real application submission has not been exercised during development.
