"""Reproducible development-only curation from the retained MIT CSV snapshot."""
import json
from pathlib import Path

from .registry import import_jobseek


def main():
    project = Path(__file__).resolve().parents[3]
    # backend/ is parents[2]; repository root is parents[3].
    base = project / "research/repositories/jobseek/apps/crawler/data"
    selected = json.loads(Path(__file__).with_name("seed_candidates.json").read_text())
    excluded = {"thoughtworks-new", "hp", "cadence-solutions", "fis", "angel-city", "navier",
                "dream-security", "upgrade", "physicsx", "vivo-defence-services", "neon"}
    selected = [s for s in selected if s not in excluded]
    # Keep the India IT services and AI employers toward the end of the source
    # list while trimming several large car/aircraft makers from this CSE seed.
    trim = {"mercedes-benz", "bmw", "continental", "valeo", "ford", "general-motors", "boeing", "airbus", "rtx",
            "playstation-global", "take-two-interactive-software-inc", "tesla", "aptiv", "ovhcloud", "huawei", "xiaomi", "mediatek"}
    selected = [s for s in selected if s not in trim]
    entries = import_jobseek(base / "companies.csv", base / "boards.csv", selected_slugs=set(selected))
    order = {slug: index for index, slug in enumerate(selected)}
    entries.sort(key=lambda c: order[c["provenance"]["company_slug"]])
    manual = [
        ("Tata Consultancy Services", "tcs.com", "https://www.tcs.com/careers/india"),
        ("Zoho", "zoho.com", "https://www.zoho.com/careers/"),
        ("Freshworks", "freshworks.com", "https://www.freshworks.com/company/careers/"),
        ("Chargebee", "chargebee.com", "https://www.chargebee.com/careers/"),
        ("Meesho", "meesho.io", "https://jobs.lever.co/meesho"),
        ("BrowserStack", "browserstack.com", "https://www.browserstack.com/careers"),
        ("Thoughtworks", "thoughtworks.com", "https://www.thoughtworks.com/careers"),
        ("HP", "hp.com", "https://apply.hp.com/careers"),
        ("Cadence Design Systems", "cadence.com", "https://www.cadence.com/en_US/home/company/careers.html"),
        ("FIS", "fisglobal.com", "https://careers.fisglobal.com/"),
    ]
    for name, domain, careers in manual:
        provider = "lever" if name == "Meesho" else "generic"
        entries.append({"name": name, "domain": domain, "website": "https://www." + domain, "careers_url": careers,
            "verified": True, "verification_status": "trusted_seed",
            "provenance": {"source": "curated_known_employer", "observed_at": "2026-10-02", "note": "Company legitimacy seed; live ATS association remains candidate"},
            "sources": [{"provider": provider, "url": careers, "board": None, "association_status": "candidate",
                         "enabled": True, "verified": False, "poll_interval_hours": 12, "config": {"association_status": "candidate"}}]})
    for index, item in enumerate(entries):
        item.update(verified=True, verification_status="trusted_seed")
        if item["name"] == "Rubrik Job Board":
            item["name"] = "Rubrik"
        if item["name"] == "HackerRank Careers":
            item["name"] = "HackerRank"
        if item["domain"] == "sentry.com":
            item["domain"], item["website"] = "sentry.io", "https://sentry.io"
        # Prefer structured providers, then a limited selection of regional
        # boards; all imported associations retain candidate status.
        item["sources"].sort(key=lambda s: (s["provider"] == "generic", "india" not in s["url"].lower()))
        item["sources"] = item["sources"][:3]
        for source in item["sources"]:
            source["priority"] = 1 if index < 40 else 2
            source["poll_interval_hours"] = 12 if index < 40 else 24
    assert len(entries) == 200, len(entries)
    assert len({c["domain"] for c in entries}) == 200
    destination = Path(__file__).resolve().parents[1] / "data/company_seeds.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"companies": len(entries), "sources": sum(len(c["sources"]) for c in entries)}))


if __name__ == "__main__":
    main()
