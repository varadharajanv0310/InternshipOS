# Resume uploads and GitHub projects

## Owner workflow

Open **Resumes & projects → Upload PDF**. Select a PDF up to 3 MB, optionally name it, and save it as a new resume or a new version of an existing variant. Preview it, then click **I reviewed it · Approve for applications**. Approved uploads are selectable in application packs just like generated resume versions.

The original bytes, filename, page count and SHA-256 are preserved. PDFs are stored in the private database, survive serverless filesystem resets, and are included in portable backups. Existing generated resumes and previously submitted versions remain unchanged. Uploading does not rewrite the PDF or automatically overwrite profile facts. Password-protected, unreadable, non-PDF and oversized files are rejected. Uploading/approving requires owner authentication; the paired extension can download resumes through its existing scoped endpoint.

Open **Connect GitHub** or **Settings → GitHub projects → Open project inventory**. Enter your public GitHub username and click **Connect & import**. The connection remembers the username, repository count and last sync. **Sync projects** refreshes repository evidence; **Disconnect** preserves imported projects. This is a public-profile connection, not OAuth access to private repositories.

Repository listings are paginated, excluding forks and archived repositories. Imports are bounded at 2,000 listed repositories; larger accounts return an explicit limit error instead of pretending coverage is complete. README excerpts and possible claims for the 12 most recently updated eligible repositories are review material. They appear under **Review facts** and never become approved resume bullets automatically. Existing approved descriptions and bullets survive later syncs. GitHub failures preserve the previous connection and inventory. Sync is manual; it is not a background GitHub watcher.

## Verification and deployment

- Backend regression suite: 115 passed, including original-byte download, cache loss, approval, application selection, owner/extension scopes, malformed/oversized uploads, durable backup/restore, GitHub pagination, preservation and failure handling.
- Frontend: 13 checks passed, including multipart upload boundaries and unchanged JSON writes; production build passed. Original PDFs render through a lazy-loaded PDF.js viewer instead of relying on an embedded browser PDF plugin. All resume versions are visible, and application selection lists approved versions.
- Database change: one additive `resume_artifacts` table; existing schema, profile, applications and integration credentials preserved.
- Dependencies: `pypdf>=6,<7` for PDF validation; `pdfjs-dist` 6.3.289 for in-app preview. Vite updated to 7.3.6 to resolve its reported development-server advisories; frontend audit reports zero vulnerabilities.
- Hosting: existing Vercel project and private Neon database; no new deployment project or paid provider.

## Technical references

- [GitHub repository listing API](https://docs.github.com/en/rest/repos/repos#list-repositories-for-a-user)
- [GitHub README API](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme)
- [Mozilla PDF.js rendering examples](https://mozilla.github.io/pdf.js/examples/)

Hosted verification results will be appended after deployment.
