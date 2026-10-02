# Hosting progress

- [x] Vercel and Neon accounts authenticated. Existing projects preserved.
- [x] Separate internshipos projects created; Neon Singapore PostgreSQL 16.
- [x] Personal profile imported from supplied resume (2028, CGPA 9.13).
- [x] Local archive preserved; 47 personal/review opportunities migrated with related evidence.
- [x] Production secrets configured privately, outside Git.
- [x] Successful Vercel build: Python 3.12 pinned; frontend install isolated from framework auto-install. Required seed assets included.
- [x] Production URL/origins: https://internshipos.vercel.app. PostgreSQL health, owner login and all main read endpoints verified; unauthenticated profile rejected with 401. 46 default-list opportunities, 32 with both scores; remaining evidence insufficient.
- [x] Private repository https://github.com/varadharajanv0310/InternshipOS, linked to Vercel. DATABASE_URL and TOKEN_ENCRYPTION_KEY stored as GitHub secrets; COLLECTION_ENABLED=true. Six-hour schedule.
- [ ] Collector dispatched; first run cancelled because registry setup was slow. Batched lookups fixed, replacement run 37047847136 dispatched. Outcome pending. Cloud CI passed on preceding commit.

Neon agent skill fetched for reference at data/private/hosting/NEON_SKILL_REFERENCE.md. No skill or MCP installation/configuration changes made: user asked whether the setup prompt was necessary. Existing CLI authentication already provides project access.

Google connection and AI credentials are not configured. Resume PDFs and credentials remain outside Git.
