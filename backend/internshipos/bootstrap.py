"""Idempotent installation including distinct global discovery feeds."""
from sqlalchemy import select
from .db import init_db, SessionLocal
from .seed import seed_database
from .models import Company, CompanySource

def update_managed_seed_filters(db):
    """Migrate corrected country facets without replacing owner source settings."""
    import json
    from pathlib import Path
    seeds=json.loads((Path(__file__).parent/'data/company_seeds.json').read_text(encoding='utf-8-sig'))
    companies={c.name:c for c in db.scalars(select(Company)).all()}
    sources={(r.company_id,r.provider,r.url):r for r in db.scalars(select(CompanySource)).all()}
    for item in seeds:
        company=companies.get(item['name'])
        if not company or not company.metadata_json.get('seed'):continue
        for candidate in item.get('sources',[]):
            row=sources.get((company.id,candidate['provider'],candidate['url']))
            if not row or not row.config.get('registry_source'):continue
            cfg=candidate.get('config',{});updates={k:cfg[k] for k in ('country_name','early_career') if k in cfg}
            if row.provider=='amazon' and 'params' in cfg:updates['params']={**row.config.get('params',{}),**cfg['params']}
            if updates:row.config={**row.config,**updates}
    db.commit()

def update_classification_rules(db):
    from .models import Setting,Opportunity,Activity
    from .domain import classify
    from .service import _evaluate_and_store
    version='title-exclusions-and-sde-v5'
    row=db.get(Setting,'classification_rules')
    if row and row.value==version:return
    changed=[]
    for op in db.scalars(select(Opportunity)).all():
        result=classify(op.description,op.title)
        if result['role_family']!=op.role_family:
            changed.append({'id':op.id,'before':op.role_family,'after':result['role_family']});op.role_family=result['role_family'];_evaluate_and_store(db,op)
    db.merge(Setting(key='classification_rules',value=version))
    if changed:db.add(Activity(kind='classification',title='Role relevance rules updated',data={'rule_version':version,'changes':changed}))
    db.commit()

def install_discovery_sources(db):
    from .ingestion.registry import default_discovery_sources
    holder=db.scalars(select(Company).where(Company.name=='Discovery feeds')).first()
    if not holder:
        holder=Company(name='Discovery feeds',metadata_json={'source_holder':True},verified=False);db.add(holder);db.flush()
    existing_keys=set(db.execute(select(CompanySource.company_id,CompanySource.provider,CompanySource.url)).all())
    for source in default_discovery_sources():
        existing=(holder.id,source['provider'],source['url']) in existing_keys
        if not existing:
            db.add(CompanySource(company_id=holder.id,provider=source['provider'],url=source['url'],config={**source.get('config',{}),'name':source['name']},priority=1,cadence_hours=source['cadence_hours'],enabled=source['enabled'],verified=False,status='pending' if source['enabled'] else 'manual_capture'))
    db.commit()


def install_previous_board_candidates(db):
    """Old observed mappings are candidate evidence, never automatic trust."""
    import json
    from pathlib import Path
    from .company_priority import default_priority
    path=Path(__file__).parent/'data/previous_tracker_boards.json'
    if not path.exists():return 0
    added=0
    companies={c.name.lower():c for c in db.scalars(select(Company)).all()}
    existing_keys=set(db.execute(select(CompanySource.company_id,CompanySource.provider,CompanySource.url)).all())
    for item in json.loads(path.read_text()):
        company=companies.get(item['company'].lower())
        if not company:
            company=Company(name=item['company'],verified=False,metadata_json={'previous_project':True});db.add(company);db.flush();companies[item['company'].lower()]=company
        exists=(company.id,item['provider'],item['url']) in existing_keys
        if exists:continue
        db.add(CompanySource(company_id=company.id,provider=item['provider'],url=item['url'],config={**item['config'],'registry_source':'owner_previous_tracker','association_status':'candidate','association_evidence':item['evidence']},enabled=default_priority(company.name)['score']>=75,verified=False,priority=1 if default_priority(company.name)['score']==100 else 2,cadence_hours=24,status='pending'))
        existing_keys.add((company.id,item['provider'],item['url']))
        added+=1
    db.commit()
    return added

def bootstrap():
    init_db()
    with SessionLocal() as db:
        result=seed_database(db);update_managed_seed_filters(db);update_classification_rules(db);install_discovery_sources(db);install_previous_board_candidates(db);install_previous_companies(db)
        from .company_priority import install_priorities
        install_priorities(db);install_owner_search_policy(db)
    return result



def install_previous_companies(db):
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    companies={c.name.lower():c for c in db.scalars(select(Company)).all()}
    bound=set(db.scalars(select(CompanySource.company_id)).all())
    for item in json.loads((Path(__file__).parent/'data/previous_tracker_companies.json').read_text()):
        c=companies.get(item['name'].lower())
        if not c:
            c=Company(name=item['name'],careers_url=item['careers_url'],domain=urlsplit(item['careers_url']).hostname,verified=False,metadata_json={'previous_project':True});db.add(c);db.flush();companies[c.name.lower()]=c
        if not c.careers_url:c.careers_url=item['careers_url']
        if c.id not in bound:
            db.add(CompanySource(company_id=c.id,provider='generic',url=item['careers_url'],enabled=True,verified=False,priority=2,cadence_hours=48,config={'registry_source':'owner_previous_tracker','association_status':'candidate'},status='pending'));bound.add(c.id)
    db.commit()

def install_owner_search_policy(db):
    from .models import Setting
    flag=db.get(Setting,'personal_target_filter')
    if not flag or not flag.value or db.get(Setting,'owner_search_policy_v2'):return
    for key,value in {'personal_location_policy':True,'locations':['Bengaluru','Chennai','Remote India','India unspecified'],'default_sort':'company_priority'}.items():db.merge(Setting(key=key,value=value))
    db.add(Setting(key='owner_search_policy_v2',value=True));db.commit()

if __name__=='__main__':print(bootstrap())
