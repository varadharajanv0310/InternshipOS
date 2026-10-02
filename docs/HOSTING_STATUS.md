# Hosting progress

- [x] Vercel and Neon accounts authenticated. Existing projects preserved.
- [x] Separate internshipos projects created; Neon Singapore PostgreSQL 16.
- [x] Personal profile imported from supplied resume (2028, CGPA 9.13).
- [x] Local archive preserved; 47 personal/review opportunities migrated with related evidence.
- [x] Production secrets configured privately, outside Git.
- [x] Successful Vercel build: Python 3.12 pinned; frontend install isolated from framework auto-install. Required seed assets included.
- [x] Production URL/origins: https://internshipos.vercel.app. PostgreSQL health, owner login and all main read endpoints verified; unauthenticated profile rejected with 401. 46 default-list opportunities, 32 with both scores; remaining evidence insufficient.
- [x] Private repository https://github.com/varadharajanv0310/InternshipOS, linked to Vercel. DATABASE_URL and TOKEN_ENCRYPTION_KEY stored as GitHub secrets; COLLECTION_ENABLED=true. Six-hour schedule.
- [x] Collector enabled and dispatched: run 37047847136 completed registry setup and entered collection. Live PostgreSQL fetch-run count increased from 272 to 274 and opportunity count from 47 to 49, confirming cloud writes.
- [ ] First full collector run completion pending; inspect https://github.com/varadharajanv0310/InternshipOS/actions/runs/37047847136 before declaring the whole scan successful. The earlier slow bootstrap run was cancelled and batched lookups fixed. Latest code cloud CI passed.

Neon agent skill fetched for reference at data/private/hosting/NEON_SKILL_REFERENCE.md. No skill or MCP installation/configuration changes made: user asked whether the setup prompt was necessary. Existing CLI authentication already provides project access.

Google connection and AI credentials are not configured. Resume PDFs and credentials remain outside Git.

Login password: data/private/hosting/owner-login.txt (local, ignored). Complete private endpoint results: data/private/hosting/endpoint-verification.json. Secrets and profile content are outside Git. No Neon skill/MCP installation occurred; the optional setup prompt was explained. Existing Vercel internship-radar and Neon pds-global projects were not changed.
