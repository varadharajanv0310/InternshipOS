"""Explicit low-volume read-only integration check; never runs on import."""
import asyncio
import json
from pathlib import Path

from . import collect_source


async def main():
    targets = [
        {"provider": "greenhouse", "url": "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited", "company_name": "Razorpay", "company_domain": "razorpay.com"},
        {"provider": "ashby", "url": "https://jobs.ashbyhq.com/posthog", "company_name": "PostHog", "company_domain": "posthog.com"},
        {"provider": "lever", "url": "https://jobs.lever.co/meesho", "company_name": "Meesho", "company_domain": "meesho.io"},
        {"provider": "unstop", "url": "https://unstop.com/internships", "config": {"pages": 1}},
        {"provider": "freehire", "url": "https://freehire.me/api/v1/agent/jobs/search", "config": {"params": {"limit": 3}}},
        {"provider": "workday", "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "company_name": "NVIDIA", "company_domain": "nvidia.com", "config": {"search_text": "intern"}},
        {"provider": "eightfold", "url": "https://apply.careers.microsoft.com/careers", "company_name": "Microsoft", "company_domain": "microsoft.com", "config": {"query": "intern"}},
        {"provider": "amazon", "url": "https://www.amazon.jobs/en/search", "company_name": "Amazon", "company_domain": "amazon.com", "config": {"base_query": "intern", "normalized_country_code[]": "IND"}},
    ]
    limit = asyncio.Semaphore(3)
    destination = Path(__file__).with_name("fixtures")
    async def one(source):
        async with limit:
            result = await collect_source(source, max_pages=1, max_details=2, max_requests=5, timeout_seconds=35)
            sample = result.as_dict()
            sample["jobs"] = sample["jobs"][:2]
            (destination / f"live_{source['provider']}.json").write_text(json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"provider": source["provider"], "jobs": result.observed_count, "descriptions": result.metadata.get("description_count"),
                    "complete": result.complete, "scope": result.coverage_scope, "error": result.error, "metadata": result.metadata}
    results = await asyncio.gather(*(one(x) for x in targets))
    (destination / "live_smoke_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
