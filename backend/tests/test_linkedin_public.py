import asyncio

import httpx
import pytest
from bs4 import BeautifulSoup

from internshipos.ingestion import Source, collect_source
from internshipos.ingestion.linkedin_public import native_id, parse_card, parse_detail
from internshipos.ingestion.types import SchemaError


def card(ident, location="Chennai, India", title="Software Engineer Intern", employer="Acme"):
    return f'<div class="base-search-card" data-entity-urn="urn:li:jobPosting:{ident}"><a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/role-{ident}?trackingId=x"></a><h3 class="base-search-card__title">{title}</h3><h4 class="base-search-card__subtitle">{employer}</h4><span class="job-search-card__location">{location}</span><time datetime="2026-10-08"></time></div>'


def detail(title="Software Engineer Intern", employer="Acme", canonical=""):
    return f'{canonical}<div class="top-card-layout"><h2 class="top-card-layout__title">{title}</h2><a class="topcard__org-name-link">{employer}</a></div><section class="description"><div class="show-more-less-html__markup"><p>Build Python APIs and implement SQL queries.</p></div></section><aside><h2>Recommended role</h2><a href="https://www.linkedin.com/jobs/view/999">Unrelated</a></aside>'


def collect(handler, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source(Source("linkedin", "https://www.linkedin.com/jobs/search/", config={"search_term":"software intern", "location":"India", "results_wanted":3, "detail_target_only":True, **kwargs.pop("config", {})}),client=client,resolve_dns=False,**kwargs)
    return asyncio.run(run())


def test_lists_before_enriching_and_spends_details_only_on_personal_targets():
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        if "search" in request.url.path:
            return httpx.Response(200,text=card("101")+card("102","Mumbai, India")+card("103","Bengaluru, India"))
        return httpx.Response(200,text=detail())
    result=collect(handler,max_details=10,max_pages=3)
    assert result.complete and result.coverage_scope=="discovery"
    assert len(result.jobs)==3 and result.metadata['requests']==3
    assert result.metadata['description_target_count']==2 and result.metadata['description_complete']
    assert [x['external_id'] for x in result.jobs if x['description']]==['101','103']
    assert result.jobs[0]['canonical_url']=='https://www.linkedin.com/jobs/view/101'
    assert result.jobs[0]['company_name']=='Acme' and result.jobs[0]['company_domain'] is None
    assert calls[0].startswith('https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search')


def test_detail_budget_keeps_inventory_and_rotates_after_target_first():
    def handler(request):
        return httpx.Response(200,text=card('101')+card('102')+card('103') if 'search' in request.url.path else detail())
    result=collect(handler,max_details=1,max_pages=1,config={'detail_cursor':1})
    assert not result.complete and 'detail_limit_reached' in result.error
    assert result.metadata['inventory_complete'] and result.metadata['next_detail_cursor']==2
    assert [x['external_id'] for x in result.jobs if x['description']]==['102']


def test_empty_fragment_terminates_discovery_but_unknown_markup_does_not():
    empty=collect(lambda r:httpx.Response(200,text=''),max_details=1)
    assert empty.complete and empty.observed_count==0 and empty.coverage_scope=='discovery'
    invalid=collect(lambda r:httpx.Response(200,text='<h1>Sign in to view jobs</h1>'),max_details=1)
    assert not invalid.complete and 'linkedin_listing_schema_missing' in invalid.error


def test_access_restriction_does_not_fall_back_to_successful_empty():
    result=collect(lambda r:httpx.Response(403,text='Forbidden'),max_details=1)
    assert not result.complete and 'access_restricted' in result.error and result.observed_count==0


def test_listing_pagination_uses_actual_page_size_and_rejects_repeats():
    offsets=[]
    def handler(request):
        offsets.append(request.url.params.get('start'))
        return httpx.Response(200,text=card('101') if request.url.params['start']=='0' else card('102')+card('103'))
    result=collect(handler,max_pages=2,max_details=0)
    assert result.complete and offsets==['0','1'] and result.metadata['description_scope']=='listing_only'
    repeated=collect(lambda r:httpx.Response(200,text=card('101')),max_pages=2,max_details=0)
    assert not repeated.complete and 'repeated_page' in repeated.error


def test_bounded_pages_leave_explicit_inventory_incomplete():
    result=collect(lambda r:httpx.Response(200,text=card('101')),max_pages=1,max_details=0)
    assert not result.complete and 'page_limit_reached' in result.error
    assert not result.metadata['inventory_complete'] and result.metadata['description_complete'] is False


@pytest.mark.parametrize('url',["https://evil.example/jobs/view/123", "http://www.linkedin.com/jobs/view/123", "https://linkedin.com.evil.example/jobs/view/123", "https://user@linkedin.com/jobs/view/123", "https://www.linkedin.com/jobs/view/not-a-job"])
def test_native_identity_rejects_untrusted_addresses(url):
    assert native_id(url) is None


def test_card_native_id_must_match_link():
    malformed=card('101').replace('urn:li:jobPosting:101','urn:li:jobPosting:999')
    with pytest.raises(SchemaError,match='identity_mismatch'):
        parse_card(Source('linkedin','https://www.linkedin.com/jobs/'),BeautifulSoup(malformed,'html.parser').select_one('.base-search-card'))


@pytest.mark.parametrize('body,url,reason',[
    (detail(employer='Other'),'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/101','employer_mismatch'),
    (detail(title='Other role'),'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/101','employer_mismatch'),
    (detail(),'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/999','redirect_identity_mismatch'),
    (detail(canonical='<link rel="canonical" href="https://www.linkedin.com/jobs/view/999">'),'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/101','canonical_identity_mismatch'),
    ('<h2>Unrecognized page</h2>','https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/101','primary_schema_missing')])
def test_detail_primary_identity_is_checked_before_attaching_description(body,url,reason):
    source=Source('linkedin','https://www.linkedin.com/jobs/')
    listing=parse_card(source,BeautifulSoup(card('101'),'html.parser').select_one('.base-search-card'))
    with pytest.raises(SchemaError,match=reason):parse_detail(source,listing,body,url)


def test_detail_failure_preserves_listing_and_is_partial():
    def handler(request):
        return httpx.Response(200,text=card('101')) if 'search' in request.url.path else httpx.Response(404)
    result=collect(handler,max_details=1,config={'results_wanted':1})
    assert len(result.jobs)==1 and result.metadata['inventory_complete'] and not result.complete
    assert 'detail_fetch_failed' in result.error and result.jobs[0]['description']==''
