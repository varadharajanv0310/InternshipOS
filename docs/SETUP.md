# Run and connect InternshipOS

## Local Windows app

Python 3.11–3.13 and Node 22+ are sufficient for the main app. The optional pinned JobSpy package uses a separate Python 3.11 environment because its NumPy dependency does not support Python 3.13.

From the project folder:

```powershell
.\Start-InternshipOS.ps1 -Setup
```

Subsequent starts need no `-Setup`. Open **http://127.0.0.1:5173**. Stop with `Stop-InternshipOS.ps1`. Logs, local database, PDFs and backups live in `data/`. The launcher refuses to start over occupied ports. Keep the app running for collection; closing the browser alone does not stop the worker.

Start with **Settings → Profile**. Add only your actual education, skills, name, availability and approved bullets. Then review imported GitHub projects and create a resume variant/version. Unknown profile facts produce unknown scores. Saved jobs, preparation and filling stay separate from an application receipt.

The initial 200 employers are known legitimate seed identities. Their ATS associations are separately checked through official-site links. New employers remain under review until their official identity is supported. Pause or adjust individual sources in Settings. Parser errors/challenges are visible; incomplete, filtered and failed scans never close jobs by absence.

## Google Gmail and Calendar

Create your own Google OAuth web client, enable Gmail API and Calendar API, add yourself as a permitted test user where necessary, and configure:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/integrations/google/callback
```

Put values in a local `.env` copied from `.env.example`, restart the API, then choose **Settings → Integrations → Connect Google**. Use exactly the configured redirect URI in Google's client. Gmail requests read-only access; Calendar requests the app-created calendar scope. Testing-mode token availability and consent requirements are controlled by your Google project.

Polling defaults to 45 minutes. Exact identities and high-confidence recruiting events can update applications. Ambiguous matches and uncertain times require review. Undo restores the stage/submission state and cancels email-created reminders. Calendar synchronization uses a dedicated InternshipOS calendar and respects manual event edits. No account has been connected or private mailbox/calendar accessed during development.

## Optional AI

Set `OPENAI_API_KEY` and enable AI in Settings only when wanted. The default hard ledger ceiling is $2.50/month; the maximum permitted setting is $3. Zero budget pauses optional inference. Failed/lost responses conservatively consume their reservation. Collection, rules, resumes and tracking continue without AI.

`AI_PROVIDER=openai` uses standard Responses requests. Luna is the cheap tier and Sol the explicit analysis/draft tier. Prices were checked against [official pricing](https://developers.openai.com/api/docs/pricing) on 2 October 2026; recheck before changing models. A custom paid model requires both declared input/output prices. `AI_PROVIDER=compatible` targets an HTTPS OpenAI-compatible JSON-schema endpoint; `local` targets a loopback compatible server with zero provider cost. Native APIs can be added at `providers.py` without changing the ledger/domain. Alternate provider quality has not been benchmarked. No paid request was made during verification.

AI drafts cite approved facts, reject unsupported numeric/known-technology claims, and require review. Draft text is never automatically inserted into an approved resume version.

## Browser extension

Load the `extension/` folder as an unpacked Manifest V3 extension in Chrome/Edge. Generate a pairing token in **Settings → Integrations → Browser companion**. Paste the workspace API URL and token into the extension.

Use Capture for any public job page. For applications, create a Ready application in the app, choose an approved version, refresh the extension's application list, and fill. Sensitive/legal answers stay in local extension storage; the server never receives browser cookies/passwords/OTPs.

Auto-apply is off by default. It requires provider opt-in in Settings plus the checkbox for this particular attended application. Supported provider boundaries are Greenhouse, Lever and Ashby. Unknown required fields, CAPTCHA, a different job page, missing facts or an unattached requested resume stop submission. Dynamic/custom widgets and navigation-heavy flows may need manual completion. A visible recognized confirmation receipt is required to mark Applied. Only a PDF actually attached by the extension is recorded as its submitted version. Selected application context persists across popup closure/navigation. Fixture tests cover the guards; no live employer submission was tested.

## Backups

**Settings → Backups → Export** downloads a portable ZIP of records and existing resume PDFs. Keep a copy on another device. The local app retains the latest ten exports; a hosted temporary filesystem is not durable backup storage.

Authentication keys and Google tokens are excluded. Reconnect Google after restore. To restore, stop the app and point `DATABASE_URL` at a new empty database:

```powershell
$env:PYTHONPATH='backend'
$env:DATABASE_URL='sqlite:///./data/restored.db'
backend/.venv/Scripts/python.exe -m internshipos.backup restore 'C:/path/to/internshipos-backup.zip'
```

Restore refuses to overwrite existing records, checks resume hashes, preserves history and disables auto-apply until reauthorized. Backups contain your profile/application data; store them privately. Keep your configured token encryption key separately if retaining the original database with encrypted Google credentials.

## Free hosting path

The repository includes a Vercel frontend/Python API entry, PostgreSQL-compatible schema/bootstrap and hourly GitHub Actions collection. These configurations have not been deployed to an external account.

1. Put this project in your own GitHub repository.
2. Create your own PostgreSQL database and set `DATABASE_URL` with TLS for the hosted database. SQLite is the local fallback only.
3. Import the project into Vercel using `vercel.json`. Configure `PUBLIC_BASE_URL`, `FRONTEND_URL`, `ALLOWED_ORIGINS` to your actual HTTPS origin; set a long `OWNER_PASSWORD`, stable random `AUTH_SECRET`, and Fernet `TOKEN_ENCRYPTION_KEY`. Hosted startup requires these. Set `SCHEDULER_ENABLED=false`, `APP_DATA_DIR=/tmp/internshipos`, `PDF_ENGINE=reportlab`.
4. Use the same database/encryption key in repository secrets for `collect.yml`. Set repository variable `COLLECTION_ENABLED=true` after configuring the database. Optional Google secrets are needed only for connected polling. Workflows install dependencies, bootstrap and process bounded due-source batches. Provider keys are unnecessary for collection.
5. Run the test workflow, confirm hosted session/OAuth/collection/PDF behavior, then monitor Sources and backup health.

The API serves ordinary requests; scraper workloads belong in CI/persistent workers, not request-time serverless functions. Free plan runtime, compute and CI quotas must be checked in your accounts; uninterrupted hosting or source success is not guaranteed. No paid infrastructure/proxy service is required by the app. Backups must be downloaded or scheduled to an owner-controlled destination. `compose.yml` is an optional PostgreSQL/API alternative once Docker is working; external TLS/static hosting remains the operator's configuration. Do not expose the password-free local API outside loopback.

## Verification

```powershell
$env:PYTHONPATH='backend'
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build
npm test
cd ../extension
npm ci
npm test
```

Tests use isolated fixtures and do not access personal accounts, spend AI money or submit applications. PostgreSQL DDL/CI configuration exists; the local run used SQLite because Docker's engine was unavailable. Live hosted PostgreSQL, Google OAuth/token refresh and real employer auto-apply remain account-dependent validation.
