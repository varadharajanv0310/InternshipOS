"""Regression cases for the observed Workday later-page zero-total contract."""
import asyncio
import json

import httpx
import pytest

from internshipos.ingestion import collect_source
from internshipos.ingestion.adapters import workday_listing_identifiers


def listings(start, end):
    return [{"title": "Software Intern", "externalPath": f"/job/Chennai/Software-Intern_R{i}",
             "bulletFields": [f"R{i}"], "locationsText": "Chennai"} for i in range(start, end)]


def run(pages, *, config=None, **options):
    calls = []
    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json=pages(body, len(calls)))
        ident = request.url.path.rsplit("_", 1)[-1]
        return httpx.Response(200, json={"jobPostingInfo": {
            "jobReqId": ident, "title": "Software Intern", "location": "Chennai",
            "jobDescription": "Build Python software and test public APIs."}})
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source({"provider": "workday", "url": "https://fixture.wd5.myworkdayjobs.com/External",
                                         "company_name": "Fixture", "config": config or {}},
                                        client=client, resolve_dns=False, **options)
    return asyncio.run(collect()), calls


@pytest.mark.parametrize("config,scope", [({}, "full"), ({"search_text": "intern"}, "query")])
def test_later_zero_total_retains_head_and_collects_all_distinct_jobs(config, scope):
    result, calls = run(lambda body, _: {
        "total": 41 if body["offset"] == 0 else 0,
        "jobPostings": listings(body["offset"], min(41, body["offset"] + 20))}, config=config)
    assert [body["offset"] for body in calls] == [0, 20, 40]
    assert result.complete and result.coverage_scope == scope
    assert result.metadata["inventory_complete"] and result.metadata["reported_total"] == 41
    assert len(result.jobs) == 41 and {job["external_id"] for job in result.jobs} == {f"R{i}" for i in range(41)}
    assert all(job["description"] for job in result.jobs)
    assert "inventory_changed_during_scan" not in (result.error or "")


def test_contradictory_positive_total_is_still_incomplete():
    result, _ = run(lambda body, _: {
        "total": 30 if body["offset"] == 0 else 29,
        "jobPostings": listings(body["offset"], min(30, body["offset"] + 20))})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "inventory_changed_during_scan" in result.error
    assert result.metadata["reported_total"] == 30


def test_zero_head_with_empty_inventory_remains_explicit_absence_proof():
    result, _ = run(lambda body, _: {"total": 0, "jobPostings": []})
    assert result.complete and result.coverage_scope == "full"
    assert result.metadata["inventory_complete"] and result.metadata["reported_total"] == 0
    assert not result.jobs


def test_zero_head_with_jobs_cannot_claim_complete():
    result, _ = run(lambda body, _: {"total": 0, "jobPostings": listings(0, 1)})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "inventory_changed_during_scan" in result.error


def test_zero_later_total_with_early_empty_page_is_not_a_sentinel():
    result, _ = run(lambda body, _: {
        "total": 30 if body["offset"] == 0 else 0,
        "jobPostings": listings(0, 20) if body["offset"] == 0 else []})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "workday_pagination_incomplete_or_repeated" in result.error
    assert result.metadata["reported_total"] == 30


@pytest.mark.parametrize("second", [listings(0, 10), listings(10, 30), [{"title": "Software Intern"}]])
def test_zero_later_total_requires_valid_distinct_records(second):
    result, _ = run(lambda body, _: {
        "total": 30 if body["offset"] == 0 else 0,
        "jobPostings": listings(0, 20) if body["offset"] == 0 else second})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "workday_pagination_incomplete_or_repeated" in result.error


def test_resumed_listing_uses_fresh_head_and_preserves_bound_and_cursor():
    result, calls = run(lambda body, _: {
        "total": 45 if body["offset"] == 0 else 0,
        "jobPostings": listings(body["offset"], min(45, body["offset"] + 20))},
        config={"listing_cursor": 20}, max_pages=1)
    assert [body["offset"] for body in calls] == [0, 20]
    assert not result.complete and not result.metadata["inventory_complete"]
    assert result.coverage_scope == "query" and result.metadata["reported_total"] == 45
    assert result.metadata["next_listing_cursor"] == 40
    assert "page_limit_reached" in result.error and "inventory_changed_during_scan" not in result.error


def test_resumed_head_uses_final_facets_instead_of_discovery_or_cached_count():
    def pages(body, number):
        if number == 1:
            return {"total": 1000, "jobPostings": [], "facets": [
                {"facetParameter": "locationCountry", "values": [{"id": "IN", "descriptor": "India"}]},
                {"facetParameter": "workerSubType", "values": [{"id": "INTERN", "descriptor": "Intern"}]}]}
        assert body["searchText"] == ""
        assert body["appliedFacets"] == {"locationCountry": ["IN"], "workerSubType": ["INTERN"]}
        return {"total": 27 if body["offset"] == 0 else 0,
                "jobPostings": listings(body["offset"], min(27, body["offset"] + 20))}
    result, calls = run(pages, config={"listing_cursor": 20, "search_text": "intern",
                                     "country_name": "India", "early_career": True,
                                     "board_health": {"reported_total": 999}}, max_pages=1)
    assert [body["offset"] for body in calls] == [0, 0, 20]
    assert result.metadata["reported_total"] == 27 and result.metadata["next_listing_cursor"] == 0
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "inventory_changed_during_scan" not in result.error


def test_country_and_type_facets_are_discovered_without_keyword_hiding_regional_roles():
    def pages(body, number):
        if number == 1:
            assert body['searchText'] == '' and body['offset'] == 0
            return {'total': 1000, 'jobPostings': [], 'facets': [
                {'facetParameter': 'locationCountry', 'values': [{'id': 'IN', 'descriptor': 'India'}]},
                {'facetParameter': 'workerSubType', 'values': [{'id': 'INTERNS', 'descriptor': 'Intern'}]}]}
        assert body['appliedFacets'] == {'locationCountry': ['IN'], 'workerSubType': ['INTERNS']}
        return {'total': 1, 'jobPostings': listings(0, 1)}
    result, calls = run(pages, config={'country_name': 'India', 'early_career': True, 'search_text': 'intern'})
    assert result.complete and result.coverage_scope == 'query' and len(result.jobs) == 1


@pytest.mark.parametrize("invalid", [None, True, -1, "30"])
def test_invalid_later_total_is_not_treated_as_zero_sentinel(invalid):
    result, _ = run(lambda body, _: {
        "total": 30 if body["offset"] == 0 else invalid,
        "jobPostings": listings(body["offset"], min(30, body["offset"] + 20))})
    assert not result.complete and "missing_workday_total" in result.error


def test_zero_sentinel_does_not_remove_large_board_partitioning_requirement():
    result, _ = run(lambda body, _: {
        "total": 2000 if body["offset"] == 0 else 0,
        "jobPostings": listings(body["offset"], body["offset"] + 20)}, max_pages=2)
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "workday_query_cap_requires_partitioning" in result.error
    assert result.metadata["reported_total"] == 2000 and result.metadata["next_listing_cursor"] == 40


def test_zero_later_total_cannot_hide_records_exceeding_authoritative_count():
    result, _ = run(lambda body, _: {
        "total": 21 if body["offset"] == 0 else 0,
        "jobPostings": listings(body["offset"], body["offset"] + 20)})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "inventory_changed_during_scan" in result.error
    assert result.metadata["reported_total"] == 21


def test_resumed_positive_head_with_missing_records_stays_incomplete():
    result, _ = run(lambda body, _: {
        "total": 30 if body["offset"] == 0 else 0,
        "jobPostings": [] if body["offset"] == 0 else listings(20, 30)}, config={"listing_cursor": 20})
    assert not result.complete and not result.metadata["inventory_complete"]
    assert "workday_pagination_incomplete_or_repeated" in result.error


def test_location_first_bullets_do_not_merge_roles_or_skip_target_details():
    def pages(body, _):
        jobs = listings(body["offset"], min(32, body["offset"] + 20))
        for item in jobs:
            item["bulletFields"] = ["India, Chennai", item["bulletFields"][0]]
        return {"total": 32 if body["offset"] == 0 else 0, "jobPostings": jobs}
    result, _ = run(pages, config={"detail_target_only": True})
    assert result.complete and result.metadata["inventory_complete"]
    assert len(result.jobs) == 32 and {item["external_id"] for item in result.jobs} == {f"R{i}" for i in range(32)}
    assert all(item["description"] for item in result.jobs)


def test_duplicate_post_paths_share_proven_req_but_remain_distinct_records():
    base = "/job/Chennai/Software-Intern_JR1"
    rows = [{"title": "Software Intern", "externalPath": path,
             "bulletFields": ["India, Chennai", "JR1"], "locationsText": "Chennai"}
            for path in (base, base + "-1")]
    result, _ = run(lambda body, _: {"total": 2, "jobPostings": rows}, config={"detail_target_only": True})
    assert result.complete and result.metadata["inventory_complete"]
    assert {item["external_id"] for item in result.jobs} == {"JR1", base + "-1"}
    assert all(item["description"] for item in result.jobs)
    assert workday_listing_identifiers(rows[0]) == ("JR1", "JR1")
    assert workday_listing_identifiers(rows[1]) == (base + "-1", "JR1")


@pytest.mark.parametrize("bullets", [["India, Chennai"], [], ["Unrelated administrative value", "12"]])
def test_unproven_bullets_use_unique_path_without_inventing_req(bullets):
    path = "/job/Chennai/Software-Intern_A123"
    assert workday_listing_identifiers({"externalPath": path, "bulletFields": bullets}) == (path, None)
