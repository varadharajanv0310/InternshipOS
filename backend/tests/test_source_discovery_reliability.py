import asyncio

import httpx
import pytest

from internshipos.ingestion.discovery import detect_source, discover_company


@pytest.mark.parametrize('url,provider,board,token', [
    ('https://api.lever.co/v0/postings/acme?mode=json', 'lever', 'https://jobs.lever.co/acme', 'acme'),
    ('https://api.eu.lever.co/v0/postings/acme/123', 'lever', 'https://jobs.eu.lever.co/acme', 'acme'),
    ('https://api.ashbyhq.com/posting-api/job-board/acme', 'ashby', 'https://jobs.ashbyhq.com/acme', 'acme'),
    ('https://api.smartrecruiters.com/v1/companies/Acme/postings', 'smartrecruiters', 'https://careers.smartrecruiters.com/Acme', 'Acme'),
    ('https://boards-api.greenhouse.io/v1/boards/acme/jobs/123', 'greenhouse', 'https://job-boards.greenhouse.io/acme', 'acme'),
    ('https://boards.greenhouse.io/embed/job_board?for=acme', 'greenhouse', 'https://job-boards.greenhouse.io/acme', 'acme'),
    ('https://boards.eu.greenhouse.io/embed/job_board?for=acme', 'greenhouse', 'https://job-boards.eu.greenhouse.io/acme', 'acme'),
])
def test_public_api_and_embedded_links_extract_real_employer(url, provider, board, token):
    source = detect_source(url)
    assert source['provider'] == provider
    assert source['url'] == board
    assert source['config']['token'] == token
    assert source['verified'] is False


@pytest.mark.parametrize('url', [
    'https://api.lever.co/v1/postings/private-id',
    'https://api.ashbyhq.com/job.list',
    'https://api.smartrecruiters.com/v1/companies',
    'https://boards.greenhouse.io/embed/job_board',
    'https://boards.greenhouse.io/embed/job_board?for=acme%2Fother',
    'https://apply.workable.com/j/ABC123',
    'https://user:password@jobs.lever.co/acme',
    'https://jobs.lever.co.evil.example/acme',
])
def test_incomplete_or_private_api_links_cannot_become_bogus_boards(url):
    assert detect_source(url) is None


def test_verified_official_careers_redirect_is_binding_evidence():
    requests = []
    def handler(request):
        requests.append(str(request.url))
        if request.url.host == 'acme.example.com':
            return httpx.Response(302, headers={'location': 'https://jobs.ashbyhq.com/acme'})
        # Other third-party links must not bind another board to Acme.
        return httpx.Response(200, text='<a href="https://jobs.ashbyhq.com/other">Other board</a>')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await discover_company('Acme', 'acme.example.com', 'https://acme.example.com/careers',
                                            trusted_domain=True, client=client, resolve_dns=False)
            assert requests[0] == 'https://acme.example.com/careers'
            assert len(result['sources']) == 1
            assert result['sources'][0]['url'] == 'https://jobs.ashbyhq.com/acme'
            assert result['sources'][0]['verified'] is True
            assert result['sources'][0]['config']['association_evidence']['linked_from'] == 'https://acme.example.com/careers'
            assert any(e['kind'] == 'official_careers_redirect' for e in result['evidence'])
    asyncio.run(run())


def test_unverified_official_redirect_does_not_assert_employer_identity():
    def handler(request):
        if request.url.host == 'acme.example.com':
            return httpx.Response(302, headers={'location': 'https://jobs.ashbyhq.com/acme'})
        return httpx.Response(200, text='Acme careers')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await discover_company('Acme', 'acme.example.com', client=client, resolve_dns=False)
            assert result['sources'][0]['verified'] is False
            assert result['sources'][0]['association_status'] == 'candidate'
    asyncio.run(run())


def test_supplied_official_careers_page_is_checked_before_blocked_marketing_homepage():
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == '/careers':
            return httpx.Response(200, text='<a href="https://api.lever.co/v0/postings/acme?mode=json">Open jobs</a>')
        return httpx.Response(403)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await discover_company('Acme', 'acme.example.com', 'https://acme.example.com/careers',
                                            trusted_domain=True, client=client, resolve_dns=False)
            assert requests == ['/careers']
            assert result['sources'][0]['url'] == 'https://jobs.lever.co/acme'
            assert result['sources'][0]['verified'] is True
    asyncio.run(run())


def test_official_greenhouse_script_embed_exposes_actual_board_without_fetching_script():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,
                text='<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'))) as client:
            result = await discover_company('Acme', 'acme.example.com', trusted_domain=True, client=client, resolve_dns=False)
            assert result['sources'][0]['url'] == 'https://job-boards.greenhouse.io/acme'
            assert result['sources'][0]['verified'] is True
    asyncio.run(run())


def test_official_culture_page_can_lead_to_separate_open_positions_page():
    def handler(request):
        pages = {
            '/': '<a href="/join-us">Careers</a>',
            '/join-us': '<a href="/open-positions">View open positions</a>',
            '/open-positions': '<a href="https://jobs.ashbyhq.com/acme/123">Software Intern</a>',
        }
        return httpx.Response(200, text=pages[request.url.path])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await discover_company('Acme', 'acme.example.com', trusted_domain=True, client=client, resolve_dns=False)
            assert result['sources'][0]['url'] == 'https://jobs.ashbyhq.com/acme'
            assert result['sources'][0]['verified'] is True
            assert result['sources'][0]['config']['association_evidence']['linked_from'] == 'https://acme.example.com/open-positions'
    asyncio.run(run())
