"""Regression for the live public Internshala card structure, no real network."""
import asyncio
from pathlib import Path
import httpx

from internshipos.ingestion import Source, collect_source
from internshipos.ingestion.adapters import parse_internshala
from internshipos.search_policy import retain_new_candidate

URL='https://internshala.com/internships/computer-science-internship/'
HTML=(Path(__file__).parent/'fixtures/internshala_listing_v2.html').read_text(encoding='utf-8')
FINAL='''<div class="individual_internship"><h2 class="job-internship-name"><a class="job-title-href" href="/internship/detail/backend-development-internship-in-chennai-at-final1790000002">Backend Development</a></h2><div class="company_name"><p class="company-name">Final employer</p><span>Actively hiring</span></div><div class="locations">Chennai</div></div>'''


def collect(handler, **limits):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source(Source('internshala',URL,config=limits.pop('config',{})),client=client,resolve_dns=False,**limits)
    return asyncio.run(run())


def test_real_card_title_and_employer_do_not_include_hiring_badge():
    jobs=parse_internshala(Source('internshala',URL),HTML,URL)
    assert len(jobs)==3
    assert [job['title'] for job in jobs]==['Operations','Full Stack Development','Software Development']
    assert [job['company_name'] for job in jobs]==['CyberFrat','She Can Foundation','Fixture employer']
    assert all('/internship/detail/' in job['canonical_url'] for job in jobs)


def test_real_card_locations_keep_remote_and_chennai_targets_only():
    jobs=parse_internshala(Source('internshala',URL),HTML,URL)
    assert retain_new_candidate(jobs[0]) is False
    assert retain_new_candidate(jobs[1]) is True
    assert retain_new_candidate(jobs[2]) is True


def test_next_page_is_checked_before_discovery_scope_can_complete():
    requests=[]
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200,text=FINAL if '/page-2/' in request.url.path else HTML)
    result=collect(handler,max_pages=3,max_details=0)
    assert len(requests)==2 and '/page-2/' in requests[-1]
    assert len(result.jobs)==4 and result.complete
    assert result.coverage_scope=='discovery'


def test_page_budget_persists_cursor_without_complete_inventory_proof():
    result=collect(lambda request:httpx.Response(200,text=HTML),max_pages=1,max_details=0)
    assert not result.complete and result.coverage_scope=='discovery'
    assert result.metadata['next_listing_cursor']==1


def test_repeated_next_page_cannot_prove_complete_discovery():
    requests=[]
    def handler(request):
        requests.append(str(request.url));return httpx.Response(200,text=HTML)
    result=collect(handler,max_pages=3,max_details=0)
    assert not result.complete and len(result.jobs)==3
    assert result.coverage_scope=='discovery' and len(requests)<=3


def test_continued_segment_is_not_a_complete_inventory():
    result=collect(lambda request:httpx.Response(200,text=FINAL),max_pages=3,max_details=0,config={'listing_cursor':1})
    assert len(result.jobs)==1
    assert not result.complete and result.coverage_scope=='discovery'
