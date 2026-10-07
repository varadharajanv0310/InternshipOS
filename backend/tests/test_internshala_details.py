"""Public JD enrichment preserves the enumerated role's identity and evidence."""
import asyncio
from pathlib import Path
import httpx

from internshipos.ingestion import Source, collect_source
from internshipos.ingestion.adapters import parse_internshala

CATEGORY='https://internshala.com/internships/software-development-internship-in-chennai/'
DETAIL_URL='https://internshala.com/internship/detail/full-stack-development-internship-in-chennai-at-voicedots-infotech1790388263'
FINAL_URL='https://internshala.com/internship/detail/backend-development-internship-in-chennai-at-final1790000002'
DETAIL=(Path(__file__).parent/'fixtures/internshala_detail_v2.html').read_text(encoding='utf-8')
FALLBACK=(Path(__file__).parent/'fixtures/internshala_detail_no_jsonld.html').read_text(encoding='utf-8')
FALLBACK_URL='https://internshala.com/internship/detail/part-time-java-full-stack-developer-internship-in-multiple-locations-at-gradtwin-services-opc-private-limited1790589363'


def card(url=DETAIL_URL,title='Full Stack Development',employer='Voicedots Infotech',location='Chennai'):
    return f'<div class="individual_internship"><h2 class="job-internship-name"><a class="job-title-href" href="{url}">{title}</a></h2><div class="company_name"><p class="company-name">{employer}</p><span>Actively hiring</span></div><div class="locations">{location}</div></div>'


def collect(handler, **limits):
    async def run():
        config=limits.pop('config',{})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect_source(Source('internshala',CATEGORY,config=config),client=client,resolve_dns=False,**limits)
    return asyncio.run(run())


def test_missing_jsonld_url_falls_back_to_exact_detail_url():
    parsed=parse_internshala(Source('internshala',CATEGORY),DETAIL,DETAIL_URL)
    assert len(parsed)==1
    assert parsed[0]['external_id']=='20263302639'
    assert parsed[0]['canonical_url']==DETAIL_URL
    assert parsed[0]['company_name']=='Voicedots Infotech'
    assert 'Build Python services' in parsed[0]['description']
    assert parsed[0]['compensation']['min']==18000
    assert 'Python' in parsed[0]['skills']


def test_detail_enrichment_preserves_listing_url_external_id():
    result=collect(lambda request:httpx.Response(200,text=card() if request.url.path.startswith('/internships/') else DETAIL),max_details=1)
    assert len(result.jobs)==1
    item=result.jobs[0]
    assert item['external_id']==DETAIL_URL and item['canonical_url']==DETAIL_URL
    assert item['company_name']=='Voicedots Infotech'
    assert 'Build Python services' in item['description']
    assert result.metadata['description_scope']=='target_candidates'
    assert result.metadata['description_complete'] is True
    assert result.coverage_scope=='discovery'


def test_wrong_employer_detail_does_not_promote_its_description():
    wrong=DETAIL.replace('Voicedots Infotech','Different employer')
    result=collect(lambda request:httpx.Response(200,text=card() if request.url.path.startswith('/internships/') else wrong),max_details=1)
    assert result.jobs[0]['company_name']=='Voicedots Infotech'
    assert result.jobs[0]['description']=='' and not result.complete
    assert result.metadata['description_complete'] is False and result.error


def test_wrong_canonical_url_in_jsonld_does_not_promote_description():
    wrong=DETAIL.replace('"title":"Full Stack Development - Internship",','"title":"Full Stack Development - Internship","url":"'+FINAL_URL+'",')
    result=collect(lambda request:httpx.Response(200,text=card() if request.url.path.startswith('/internships/') else wrong),max_details=1)
    assert result.jobs[0]['canonical_url']==DETAIL_URL
    assert result.jobs[0]['description']=='' and not result.complete


def test_redirect_to_another_role_cannot_be_enriched_as_original():
    def handler(request):
        if request.url.path.startswith('/internships/'):return httpx.Response(200,text=card())
        if str(request.url)==DETAIL_URL:return httpx.Response(302,headers={'Location':FINAL_URL})
        return httpx.Response(200,text=DETAIL)
    result=collect(handler,max_details=1)
    assert result.jobs[0]['external_id']==DETAIL_URL
    assert result.jobs[0]['description']=='' and not result.complete


def test_description_budget_rotates_target_roles_without_fetching_unwanted_city():
    listing=card('https://internshala.com/internship/detail/operations-internship-in-mumbai-at-fixture1790000003','Operations','Mumbai employer','Mumbai')+card()+card(FINAL_URL,'Backend Development','Final employer')
    requests=[]
    def handler(request):
        requests.append(str(request.url))
        if request.url.path.startswith('/internships/'):return httpx.Response(200,text=listing)
        return httpx.Response(200,text=DETAIL.replace('Voicedots Infotech','Final employer') if str(request.url)==FINAL_URL else DETAIL)
    first=collect(handler,max_details=1)
    assert first.metadata['description_target_count']==2
    assert first.metadata['description_count']==1 and not first.metadata['description_complete']
    assert first.metadata['next_detail_cursor']==1 and not first.complete
    assert all('mumbai' not in url for url in requests)
    requests.clear()
    second=collect(handler,max_details=1,config={'detail_cursor':1})
    assert [job['external_id'] for job in second.jobs if job['description']]==[FINAL_URL]
    assert all('mumbai' not in url for url in requests)


def test_html_detail_is_bound_to_main_card_not_first_related_anchor():
    parsed=parse_internshala(Source('internshala',CATEGORY),FALLBACK,FALLBACK_URL)
    assert len(parsed)==1
    assert parsed[0]['canonical_url']==FALLBACK_URL
    assert parsed[0]['company_name']=='GRADTWIN SERVICES (OPC) PRIVATE LIMITED'
    assert parsed[0]['location']=='Chennai, Tamil Nadu'
    assert parsed[0]['raw']['internship_id']=='3305152'
    assert 'Build Java APIs' in parsed[0]['description']
    assert 'Related description' not in parsed[0]['description']


def test_main_html_card_enriches_without_rebinding_identity():
    listing=card(FALLBACK_URL,'Java Full Stack Developer','GRADTWIN SERVICES (OPC) PRIVATE LIMITED')
    listing=listing.replace('class="individual_internship"','class="individual_internship" internshipid="3305152"')
    result=collect(lambda request:httpx.Response(200,text=listing if request.url.path.startswith('/internships/') else FALLBACK),max_details=1)
    assert result.jobs[0]['external_id']==FALLBACK_URL
    assert result.metadata['description_complete'] is True
    assert 'Build Java APIs' in result.jobs[0]['description']


def test_same_employer_and_url_with_different_dom_internship_id_is_rejected():
    listing=card(FALLBACK_URL,'Java Full Stack Developer','GRADTWIN SERVICES (OPC) PRIVATE LIMITED')
    listing=listing.replace('class="individual_internship"','class="individual_internship" internshipid="3305152"')
    wrong=FALLBACK.replace('individual_internship_3305152','individual_internship_9999999')
    result=collect(lambda request:httpx.Response(200,text=listing if request.url.path.startswith('/internships/') else wrong),max_details=1)
    assert result.jobs[0]['description']==''
    assert 'internship_id' in result.error and FALLBACK_URL in result.error


def test_canonical_html_conflict_is_rejected_even_if_jsonld_url_matches():
    wrong=DETAIL.replace('<head>','<head><link rel="canonical" href="'+FINAL_URL+'">')
    wrong=wrong.replace('"title":"Full Stack Development - Internship",','"title":"Full Stack Development - Internship","url":"'+DETAIL_URL+'",')
    result=collect(lambda request:httpx.Response(200,text=card() if request.url.path.startswith('/internships/') else wrong),max_details=1)
    assert result.jobs[0]['description']==''
    assert 'canonical_url' in result.error and DETAIL_URL in result.error


def test_unscoped_recommendation_markup_cannot_be_promoted_as_detail():
    wrong=FALLBACK.replace('class="detail_view"','class="unknown_layout"')
    assert parse_internshala(Source('internshala',CATEGORY),wrong,FALLBACK_URL)==[]
