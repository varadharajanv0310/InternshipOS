"""Read-only CLI: python -m internshipos.ingestion --provider ashby --url ..."""
import argparse
import asyncio
import json
from pathlib import Path

from . import collect_source


def main():
    parser = argparse.ArgumentParser(description="Collect public job data without database writes")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--company", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--config", default="{}", help="JSON source config")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-details", type=int, default=20)
    parser.add_argument("--output", help="Save result JSON here")
    args = parser.parse_args()
    result = asyncio.run(collect_source({"provider": args.provider, "url": args.url,
        "company_name": args.company, "company_domain": args.domain, "config": json.loads(args.config)},
        max_pages=args.max_pages, max_details=args.max_details))
    payload = json.dumps(result.as_dict(), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(json.dumps({"jobs": len(result.jobs), "complete": result.complete, "error": result.error,
                          "coverage_scope": result.coverage_scope, "metadata": result.metadata}))
    else:
        print(payload)


if __name__ == "__main__":
    main()
