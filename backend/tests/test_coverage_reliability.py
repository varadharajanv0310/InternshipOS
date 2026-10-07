"""Inventory, fair detail work and bounded public-search regression evidence."""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from internshipos import ingestion
from internshipos.ingestion import collect_source


def collect(provider, handler, config=None, url=None, **budgets):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({"provider": provider,
                "url": url or "https://careers.example.com/acme", "config": config or {},
                "company_name": "Acme", "company_domain": "acme.example.com"},
                client=client, resolve_dns=False, **budgets)
    return asyncio.run(run())


def workday_handler(request):
    if request.method == "POST":
        offset = json.loads(request.content)["offset"]
        return httpx.Response(200, json={"total": 41, "jobPostings": [
            {"externalPath": f"/job/Chennai/Software-Intern_R{i}", "title": "Software Intern",
             "locationsText": "Chennai, India", "bulletFields": [f"R{i}"]}
            for i in range(offset, min(41, offset + 20))]})
    ident = request.url.path.rsplit("_", 1)[-1]
    return httpx.Response(200, json={"jobPostingInfo": {"jobReqId": ident,
        "jobDescription": "Build Python APIs", "location": "Chennai, India"}})


def test_workday_inventory_finishes_before_bounded_detail_pass():
    result = collect("workday", workday_handler, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External")
    assert len(result.jobs) == 41 and result.metadata["inventory_complete"]
    assert result.metadata["inventory_observed_count"] == 41
    assert result.metadata["description_count"] == 1 and not result.complete
    assert result.metadata["next_detail_cursor"] == 1 and result.coverage_scope == "full"


def test_workday_page_budget_cannot_become_closure_proof():
    result = collect("workday", workday_handler, max_pages=1, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External")
    assert len(result.jobs) == 20 and not result.metadata["inventory_complete"]
    assert "page_limit_reached" in result.error and not result.complete


def test_workday_detail_cursor_wraps_when_inventory_shrinks():
    result = collect("workday", workday_handler, config={"detail_cursor": 100}, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External")
    assert result.metadata["inventory_complete"] and result.metadata["next_detail_cursor"] == 19
    assert [x["external_id"] for x in result.jobs if x["description"]] == ["R18"]


def test_workday_total_changes_prevent_inventory_completeness():
    def handler(request):
        response = workday_handler(request)
        if request.method == "POST" and json.loads(request.content)["offset"]:
            payload = response.json()
            payload["total"] = 40
            return httpx.Response(200, json=payload)
        return response
    result = collect("workday", handler, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External")
    assert not result.metadata["inventory_complete"]
    assert "inventory_changed_during_scan" in result.error


@pytest.mark.parametrize("provider,payload", [
    ("greenhouse", {"jobs": [], "meta": {"total": -1}}),
    ("greenhouse", {"jobs": [], "meta": {"total": False}}),
    ("smartrecruiters", {"content": [], "totalFound": -1}),
    ("oracle", {"items": [{"requisitionList": [], "TotalJobsCount": -1}]}),
    ("eightfold", {"data": {"positions": [], "count": -1}}),
    ("amazon", {"jobs": [], "hits": -1}),
])
def test_invalid_provider_total_is_not_a_successful_empty_inventory(provider, payload):
    result = collect(provider, lambda request: httpx.Response(200, json=payload))
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "invalid_reported_inventory_count" in result.error


@pytest.mark.parametrize("provider", ["smartrecruiters", "workable", "bamboohr", "breezy", "pinpoint"])
def test_single_inventory_details_rotate_and_listings_remain_visible(provider):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        records = [{"id": str(i), "shortcode": str(i), "name": "Software Intern",
                    "title": "Software Intern", "jobOpeningName": "Software Intern",
                    "location": {"city": "Chennai", "country": "IN"}} for i in range(3)]
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"content": records, "totalFound": 3})
        if request.url.path.startswith("/v1/companies/"):
            return httpx.Response(200, json={"name": "Software Intern",
                "jobAd": {"sections": {"jobDescription": {"text": "Build Python APIs"}}}})
        if "/widget/accounts/" in request.url.path:
            return httpx.Response(200, json={"jobs": records})
        if request.url.path.endswith(".md"):
            return httpx.Response(200, text="Build Python APIs")
        if request.url.path.endswith("/careers/list"):
            return httpx.Response(200, json={"result": records})
        if request.url.path.endswith("/detail"):
            return httpx.Response(200, json={"result": {"jobOpening": {"description": "Build Python APIs"}}})
        if request.url.path == "/json":
            return httpx.Response(200, json=records)
        if request.url.path == "/postings.json":
            return httpx.Response(200, json={"data": records, "links": {"next": None}})
        return httpx.Response(200, text='<script type="application/ld+json">' + json.dumps(
            {"@type": "JobPosting", "title": "Software Intern", "description": "Build Python APIs"}) + '</script>')
    first = collect(provider, handler, max_details=1)
    second = collect(provider, handler, config={"detail_cursor": first.metadata["next_detail_cursor"]}, max_details=1)
    assert len(first.jobs) == len(second.jobs) == 3
    assert first.metadata["inventory_complete"] and second.metadata["inventory_complete"]
    assert not first.complete and not second.complete
    assert [x["external_id"] for x in first.jobs if x["description"]] == ["0"]
    assert [x["external_id"] for x in second.jobs if x["description"]] == ["1"]
    assert second.metadata["next_detail_cursor"] == 2


def test_smartrecruiters_discovers_second_page_despite_one_detail_budget():
    def handler(request):
        if request.url.path.endswith("/postings"):
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json={"totalFound": 101, "content": [
                {"id": str(i), "name": "Software Intern", "location": {"city": "Chennai", "country": "IN"}}
                for i in range(offset, min(101, offset + 100))]})
        return httpx.Response(200, json={"jobAd": {"sections": {"description": {"text": "Python"}}}})
    result = collect("smartrecruiters", handler, max_details=1)
    assert len(result.jobs) == 101 and result.metadata["inventory_complete"]
    assert result.metadata["detail_requests"] == 1 and result.jobs[-1]["external_id"] == "100"


def test_target_detail_selection_preserves_existing_changed_appearances():
    details = []
    rows = [
        {"id": "us", "name": "Software Intern", "location": {"city": "San Francisco", "country": "US"}},
        {"id": "india", "name": "Software Intern", "location": {"city": "Chennai", "country": "IN"}},
        {"id": "saved", "name": "Senior Software Engineer", "location": {"city": "New York", "country": "US"}},
    ]
    def handler(request):
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"content": rows, "totalFound": 3})
        details.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"jobAd": {"sections": {"description": {"text": "Python"}}}})
    result = collect("smartrecruiters", handler,
        config={"detail_target_only": True, "retained_external_ids": ["saved"]}, max_details=2)
    assert details == ["india", "saved"] and len(result.jobs) == 3
    assert result.complete and result.metadata["inventory_complete"]
    assert result.jobs[0]["description"] == ""


def test_foreign_history_cursor_cannot_preempt_new_india_details():
    details = []
    def handler(request):
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"totalFound": 3, "content": [
                {"id": "us1", "name": "Software Engineer", "location": {"city": "New York", "country": "US"}},
                {"id": "us2", "name": "Software Engineer", "location": {"city": "New York", "country": "US"}},
                {"id": "in", "name": "Intern", "location": {"city": "Chennai", "country": "IN"}}]})
        details.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"jobAd": {"sections": {"description": {"text": "Build Python software"}}}})
    result = collect("smartrecruiters", handler, max_details=1, config={"detail_target_only": True,
        "detail_cursor": 2, "retained_detail_cursor": 1, "retained_external_ids": ["us1", "us2"]})
    assert details == ["in"] and result.metadata["next_retained_detail_cursor"] == 1
    assert result.complete and result.metadata["inventory_complete"]


def test_eightfold_page_budget_advances_separate_listing_cursor():
    offsets = []
    def handler(request):
        if request.url.path.endswith("/search"):
            offset = int(request.url.params["start"])
            offsets.append(offset)
            return httpx.Response(200, json={"data": {"count": 3, "positions": [
                {"id": str(i), "name": "Software Intern", "locations": ["Chennai, India"]}
                for i in range(offset, min(3, offset + 2))]}})
        return httpx.Response(200, json={"data": {"jobDescription": "Build Python APIs"}})
    first = collect("eightfold", handler, max_pages=1, max_details=1)
    last = collect("eightfold", handler, max_pages=1, max_details=1,
        config={"listing_cursor": first.metadata["next_listing_cursor"]})
    assert offsets == [0, 2] and first.metadata["next_listing_cursor"] == 2
    assert last.metadata["next_listing_cursor"] == 0 and last.jobs[0]["external_id"] == "2"
    assert not last.metadata["inventory_complete"] and last.coverage_scope == "query"


def test_workday_listing_cursor_reaches_later_page_without_closure_claim():
    first = collect("workday", workday_handler, max_pages=1, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External")
    next_page = collect("workday", workday_handler, max_pages=1, max_details=1,
        url="https://acme.wd1.myworkdayjobs.com/External", config={"listing_cursor": first.metadata["next_listing_cursor"]})
    assert first.metadata["next_listing_cursor"] == 20 and next_page.metadata["next_listing_cursor"] == 40
    assert next_page.jobs[0]["external_id"] == "R20"
    assert not next_page.metadata["inventory_complete"] and next_page.coverage_scope == "query"


def test_pinpoint_next_links_are_followed_before_details():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        page = request.url.params.get("page", "1")
        return httpx.Response(200, json={"data": [{"id": page, "attributes": {
            "title": "Software Intern", "description": "Python", "location": "Chennai, India"}}],
            "links": {"next": "/postings.json?page=2" if page == "1" else None}})
    result = collect("pinpoint", handler)
    assert result.complete and result.metadata["inventory_complete"] and len(calls) == 2
    assert [x["external_id"] for x in result.jobs] == ["1", "2"]


@pytest.mark.parametrize("target", ["/postings.json", "http://127.0.0.1/jobs", "https://other.example.com/jobs"])
def test_pinpoint_repeated_or_cross_origin_next_link_is_never_complete(target):
    result = collect("pinpoint", lambda request: httpx.Response(200, json={"data": [
        {"id": "1", "attributes": {"title": "Software Intern", "description": "Python"}}],
        "links": {"next": target}}))
    assert not result.complete and not result.metadata["inventory_complete"]
    assert result.metadata["requests"] == 1


@pytest.mark.parametrize("provider", ["lever", "amazon"])
def test_large_embedded_feed_page_budget_resumes_listing(provider):
    offsets = []
    def handler(request):
        offset = int(request.url.params.get("skip", request.url.params.get("offset", "0")))
        offsets.append(offset)
        records = [{"id": str(i), "text": "Software Intern", "title": "Software Intern",
                    "description": "Python", "hostedUrl": f"https://jobs.example.com/{i}",
                    "job_path": f"/en/jobs/{i}/intern"} for i in range(offset, min(150, offset + 100))]
        return httpx.Response(200, json=records if provider == "lever" else {"jobs": records, "hits": 150})
    first = collect(provider, handler, max_pages=1)
    last = collect(provider, handler, config={"listing_cursor": first.metadata["next_listing_cursor"]}, max_pages=1)
    assert offsets == [0, 100]
    assert not first.complete and not first.metadata["inventory_complete"]
    assert len(last.jobs) == 50 and last.metadata["next_listing_cursor"] == 0
    assert not last.metadata["inventory_complete"] and last.coverage_scope != "full"


def test_greenhouse_oversized_embedded_jds_fall_back_to_full_listing(monkeypatch):
    original = ingestion.PublicHTTP
    monkeypatch.setattr(ingestion, "PublicHTTP", lambda client, **kwargs: original(client, **{**kwargs, "max_bytes": 3000}))
    calls = []
    def handler(request):
        calls.append((request.url.path, dict(request.url.params)))
        listing = {"id": 9, "title": "Software Intern", "location": {"name": "Chennai, India"},
                   "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/9"}
        if request.url.path.endswith("/jobs/9"):
            return httpx.Response(200, json={**listing, "content": "Build Python APIs"})
        if request.url.params.get("content") == "true":
            listing["content"] = "X" * 7000
        return httpx.Response(200, json={"jobs": [listing], "meta": {"total": 1}})
    result = collect("greenhouse", handler)
    assert result.complete and result.metadata["inventory_complete"]
    assert result.jobs[0]["description"] == "Build Python APIs" and len(calls) == 3
    assert calls[0][1] == {"content": "true"} and calls[1][1] == {}
    assert "oversized_embedded_descriptions" in result.metadata["warnings"][0]


def test_valid_empty_detail_response_is_not_full_detail_success():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [
                {"title": "Software Intern", "externalPath": "/job/R1", "bulletFields": ["R1"]}]})
        return httpx.Response(200, json={"jobPostingInfo": {}})
    result = collect("workday", handler, url="https://acme.wd1.myworkdayjobs.com/External")
    assert result.metadata["inventory_complete"] and not result.complete
    assert "full_description_unavailable" in result.error


def test_configured_json_post_paginates_with_safe_array_mapping():
    config = {"api_url": "https://api.example.com/search", "method": "POST",
        "post_data": {"query": {"page": 0, "pageSize": 2}}, "json_path": "data.items",
        "total_path": "data.total", "pagination": {"location": "body", "param_name": "query.page"},
        "fields": {"title": "jobTitle || name", "locations": "locations[].city", "description": "description"},
        "url_template": "https://jobs.example.com/{id}"}
    pages = []
    def handler(request):
        body = json.loads(request.content)
        pages.append(body["query"]["page"])
        offset = body["query"]["page"] * 2
        return httpx.Response(200, json={"data": {"total": 3, "items": [
            {"id": i, "name": "Software Intern", "description": "Python", "locations": [{"city": "Chennai"}]}
            for i in range(offset, min(3, offset + 2))]}})
    result = collect("generic", handler, config=config)
    assert pages == [0, 1] and result.complete and result.metadata["inventory_complete"]
    assert len(result.jobs) == 3 and all(x["location"] == "Chennai" for x in result.jobs)
    assert config["post_data"]["query"]["page"] == 0


def test_configured_form_post_paginates_inside_encoded_json_parameter():
    config = {"api_url": "https://api.example.com/jobs/search", "method": "POST",
        "params": {"filterCri": json.dumps({"paginationStartNo": 0, "numberOfRecordsPerPage": 2})},
        "request_headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "json_path": "data.data[]._source", "total_path": "data.totalCount",
        "pagination": {"location": "body", "param_name": "filterCri.paginationStartNo", "increment": 2},
        "fields": {"title": "jobTitle", "description": {"path": "shortDescription"}, "locations": "location"},
        "url_template": "https://jobs.example.com/{jobUrl}"}
    offsets = []
    def handler(request):
        form = parse_qs(request.content.decode())
        offset = json.loads(form["filterCri"][0])["paginationStartNo"]
        offsets.append(offset)
        assert not request.url.query
        return httpx.Response(200, json={"data": {"totalCount": 3, "data": [{"_source": {
            "jobUrl": i, "jobTitle": "Software Intern", "shortDescription": "Python", "location": "Chennai, India"}}
            for i in range(offset, min(3, offset + 2))]}})
    result = collect("generic", handler, config=config)
    assert offsets == [0, 2] and result.complete and result.metadata["inventory_complete"]
    assert len(result.jobs) == 3


def test_configured_empty_array_is_valid_but_schema_drift_is_not():
    config = {"api_url": "https://api.example.com/search", "method": "POST", "post_data": {},
              "json_path": "jobs", "fields": {"title": "title", "url": "url"}}
    empty = collect("generic", lambda request: httpx.Response(200, json={"jobs": []}), config=config)
    bad = collect("generic", lambda request: httpx.Response(200, json={"jobs": {}}), config=config)
    assert empty.complete and empty.metadata["inventory_complete"]
    assert not bad.complete and "expected_array" in bad.error


def test_configured_declared_total_prevents_short_page_false_completeness():
    config = {"api_url": "https://api.example.com/search", "method": "POST", "post_data": {"limit": 20},
        "json_path": "jobs", "total_path": "total", "fields": {"title": "title", "url": "url"},
        "pagination": {"location": "body", "param_name": "page"}}
    result = collect("generic", lambda request: httpx.Response(200, json={"total": 40,
        "jobs": [{"id": 1, "title": "Software Intern", "url": "https://jobs.example.com/1"}]}), config=config)
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "inventory_incomplete" in result.error


def test_configured_graphql_mutation_rejected_before_any_request():
    config = {"api_url": "https://api.example.com/graphql", "method": "POST",
        "post_data": {"query": "mutation Submit { apply(job: 1) { id } }"}, "json_path": "data.jobs"}
    result = collect("generic", lambda request: pytest.fail("Write requests must never run"), config=config)
    assert not result.complete and result.metadata["requests"] == 0
    assert "write_operation_rejected" in result.error


def test_configured_mapping_does_not_execute_expressions():
    config = {"api_url": "https://api.example.com/search", "method": "POST", "post_data": {},
        "json_path": "jobs", "fields": {"title": "__import__('os').system('bad')", "url": "url"}}
    result = collect("generic", lambda request: httpx.Response(200, json={"jobs": [
        {"title": "Software Intern", "url": "https://jobs.example.com/1"}]}), config=config)
    assert not result.complete and "unsupported_path" in result.error


def test_configured_feed_preserves_native_slug_without_declared_derivation():
    config = {"api_url": "https://api.example.com/jobs", "json_path": "jobs",
        "fields": {"title": "title", "id": "req_id"},
        "url_template": "https://jobs.example.com/{language}/jobs/{slug}"}
    result = collect("generic", lambda request: httpx.Response(200, json={"jobs": [
        {"req_id": "5816", "slug": "5816", "language": "en-us", "title": "Software Intern"},
        {"req_id": "5817", "slug": "5817", "language": "en-us", "title": "Data Science Intern"}]}), config=config)
    assert result.complete and len(result.jobs) == 2
    assert [item["external_id"] for item in result.jobs] == ["5816", "5817"]
    assert [item["canonical_url"] for item in result.jobs] == [
        "https://jobs.example.com/en-us/jobs/5816", "https://jobs.example.com/en-us/jobs/5817"]


def test_configured_feed_derives_slug_only_when_explicitly_requested():
    config = {"api_url": "https://api.example.com/jobs", "json_path": "jobs",
        "fields": {"title": "title", "id": "req_id"}, "slug_fields": ["title"],
        "url_template": "https://jobs.example.com/{req_id}/{slug}"}
    result = collect("generic", lambda request: httpx.Response(200, json={"jobs": [
        {"req_id": "5816", "slug": "native-slug", "title": "Software Engineer Intern"}]}), config=config)
    assert result.complete and result.jobs[0]["canonical_url"] == "https://jobs.example.com/5816/software-engineer-intern"


def test_declared_snippet_feed_does_not_claim_full_jd_or_inventory():
    config = {"api_url": "https://api.example.com/Job_Openings", "json_path": "data",
        "inventory_unproven": True, "description_is_partial": True,
        "fields": {"title": "Job_Opening_Name", "description": "Job_Description", "url": "$url"}}
    result = collect("generic", lambda request: httpx.Response(200, json={"data": [
        {"Job_Opening_Name": "Software Intern", "Job_Description": "Build software...",
         "$url": "https://jobs.example.com/1"}]}), config=config)
    assert not result.complete and not result.metadata["inventory_complete"]
    assert result.jobs[0]["description"] == "" and not result.jobs[0]["raw"]["description_complete"]
    assert "summary_only_description" in result.metadata["warnings"][-1]


def test_known_salesforce_static_feed_has_scoped_bounded_size_allowance(monkeypatch):
    original = ingestion.PublicHTTP
    monkeypatch.setattr(ingestion, "PublicHTTP", lambda client, **kwargs: original(client, **{**kwargs, "max_bytes": 3000}))
    config = {"api_url": "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json",
        "json_path": "Report_Entry", "total_path": "Total_Jobs",
        "fields": {"id": "Job_Requisition_Ref_ID", "title": "Job_Posting_Title", "description": "Job_Description"},
        "url_template": "https://www.salesforce.com/company/careers/jobs/{Job_Requisition_Ref_ID}/"}
    payload = {"Total_Jobs": 1, "Report_Entry": [{"Job_Requisition_Ref_ID": "JR1",
        "Job_Posting_Title": "Software Intern", "Job_Description": "Build Python APIs" + " " * 4000}]}
    known = collect("generic", lambda request: httpx.Response(200, json=payload), config=config)
    other = collect("generic", lambda request: httpx.Response(200, json=payload),
        config={**config, "api_url": "https://api.example.com/jobs"})
    assert known.complete and known.metadata["inventory_complete"] and known.jobs[0]["external_id"] == "JR1"
    assert not other.complete and other.error == "response_size_limit_exceeded"


def test_known_salesforce_feed_still_rejects_payload_beyond_its_ceiling():
    config = {"api_url": "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json", "json_path": "Report_Entry"}
    result = collect("generic", lambda request: httpx.Response(200, content=b"x" * 16_000_001), config=config)
    assert not result.complete and not result.jobs and result.error == "response_size_limit_exceeded"
