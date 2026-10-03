"""Verify historical leads against live ATS data; never assume a snapshot is open."""
import asyncio,csv,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import select
from internshipos.db import SessionLocal
from internshipos import models as m
from internshipos.ingestion import collect_source
from internshipos.ingestion.discovery import detect_source
from internshipos.search_policy import location_decision,PHD_ONLY,retain_new_candidate
from internshipos.service import ingest_batch
from internshipos.domain import canonicalize_url
from internshipos.ingestion.http import PublicHTTP
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from internshipos.company_priority import default_priority

async def run():
    records=json.loads(Path('research/repositories/previous-internship-tracker/data/db.json').read_text())['roles']
    results=[];semaphore=asyncio.Semaphore(3)
    async def check(row):
        result={'company':row['company'],'role':row['role'],'location':row.get('location',''),'url':row['url'],'outcome':'unresolved','reason':''}
        if location_decision(row.get('location',''))!='allowed':result.update(outcome='outside scope',reason='Location excluded or remote eligibility not confirmed');return result
        if re.search(PHD_ONLY,row['role'],re.I):result.update(outcome='outside scope',reason='PhD/doctoral role');return result
        if '/jobs/' in urlsplit(row['url']).path and not re.search(r'intern|apprentice',row['role'],re.I):
            result.update(outcome='outside scope',reason='Historical regular-job page has no internship/apprenticeship title');return result
        detected=detect_source(row['url'])
        if (urlsplit(row['url']).hostname or '').removeprefix('www.')=='internshala.com':
            detected={'provider':'internshala','url':row['url'],'config':{}}
        if (urlsplit(row['url']).hostname or '').removeprefix('www.')=='unstop.com':
            detected={'provider':'unstop','url':row['url'],'config':{}}
        if not detected:
            # A blog lead is useful only if its outbound link resolves to a supported ATS.
            try:
                async with semaphore:
                    async with httpx.AsyncClient(timeout=20,trust_env=False) as client:
                        html=await PublicHTTP(client,max_requests=6).text(row['url'])
                links=[urljoin(row['url'],a['href']) for a in BeautifulSoup(html,'html.parser').find_all('a',href=True)]
                candidates=[(link,detect_source(link)) for link in links]
                candidates=[(link,d) for link,d in candidates if d and re.search(r'/job/|/jobs/|/posting/|[0-9a-f]{8}-',urlsplit(link).path)]
                if candidates:
                    row={**row,'url':candidates[0][0]};detected=candidates[0][1]
                else:
                    result['reason']='Blog has no recognized direct ATS job link; employer verification needed';return result
            except Exception as exc:
                result['reason']='Lead page could not be verified: '+str(exc)[:200];return result
        with SessionLocal() as db:
            sources=db.scalars(select(m.CompanySource).join(m.Company).where(m.Company.name.ilike(row['company']),m.CompanySource.provider==detected['provider'])).all()
            source=next((s for s in sources if detected['provider'] in {'greenhouse','lever','ashby','internshala'} or urlsplit(s.url).hostname==urlsplit(row['url']).hostname),None)
            if not source and detected['provider'] in {'internshala','unstop'}:
                source=db.scalar(select(m.CompanySource).where(m.CompanySource.provider==detected['provider']).limit(1))
            if not source:
                company=db.scalar(select(m.Company).where(m.Company.name.ilike(row['company'])))
                if not company:
                    company=m.Company(name=row['company'],verified=False,metadata_json={'company_priority':default_priority(row['company']),'verification_status':'candidate'})
                    db.add(company);db.flush()
                source=m.CompanySource(company_id=company.id,provider=detected['provider'],url=detected['url'],config=detected.get('config',{}),verified=False,enabled=True)
                db.add(source);db.commit();db.refresh(source)
            source_data={'id':source.id,'provider':source.provider,'url':source.url,'config':dict(source.config),'company_name':source.company.name,'company_domain':source.company.domain or ''}
        path=urlsplit(row['url']).path.rstrip('/');external=path.split('/')[-1]
        if external=='apply':external=path.split('/')[-2]
        if detected['provider']=='workday':external=external.rsplit('_',1)[-1]
        if detected['provider']=='unstop':external=external.rsplit('-',1)[-1]
        source_data['config']['refresh_jobs']=[{'external_id':external,'canonical_url':row['url'],'title':row['role']}]
        async with semaphore:response=await collect_source(source_data,timeout_seconds=40,max_details=1)
        jobs=[j for j in response.jobs if retain_new_candidate(j)]
        if jobs:
            with SessionLocal() as db:ingest_batch(db,source_data['id'],jobs,complete=False,error=response.error,coverage_scope='targeted',observed_count=len(jobs))
            result.update(outcome='live verified',reason='Current ATS detail fetched and eligible-location technical lead retained; employer association may still need review')
        else:result['reason']=(response.error or 'Live role outside technical/location policy').strip()
        if response.jobs and not jobs:result['outcome']='outside scope'
        return result
    results=await asyncio.gather(*(check(r) for r in records))
    out=Path('docs/PREVIOUS_FEED_RECONCILIATION.csv')
    with out.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['company','role','location','url','outcome','reason']);writer.writeheader();writer.writerows(results)
    from collections import Counter
    print(json.dumps(dict(Counter(r['outcome'] for r in results))))
    Path('docs/PREVIOUS_FEED_RECONCILIATION.md').write_text('# Previous feed reconciliation\n\nAll 53 leads from the previous 2 October snapshot were checked against the location/degree policy and supported live ATS detail paths. See the CSV for per-role evidence and unresolved cases. A missing or blocked page is not proof of closure. Live verification describes the job response, not confirmation of applicant eligibility.\n\n'+json.dumps(dict(Counter(r['outcome'] for r in results)),indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':asyncio.run(run())
