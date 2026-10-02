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
    for item in seeds:
        company=db.scalar(select(Company).where(Company.name==item['name']))
        if not company or not company.metadata_json.get('seed'):continue
        for candidate in item.get('sources',[]):
            row=db.scalar(select(CompanySource).where(CompanySource.company_id==company.id,CompanySource.provider==candidate['provider'],CompanySource.url==candidate['url']))
            if not row or not row.config.get('registry_source'):continue
            cfg=candidate.get('config',{});updates={k:cfg[k] for k in ('country_name','early_career') if k in cfg}
            if row.provider=='amazon' and 'params' in cfg:updates['params']={**row.config.get('params',{}),**cfg['params']}
            if updates:row.config={**row.config,**updates}
    db.commit()

def update_classification_rules(db):
    from .models import Setting,Opportunity,Activity
    from .domain import classify
    from .service import _evaluate_and_store
    version='title-exclusions-v4'
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
    for source in default_discovery_sources():
        existing=db.scalars(select(CompanySource).where(CompanySource.company_id==holder.id,CompanySource.provider==source['provider'],CompanySource.url==source['url'])).first()
        if not existing:
            db.add(CompanySource(company_id=holder.id,provider=source['provider'],url=source['url'],config={**source.get('config',{}),'name':source['name']},priority=1,cadence_hours=source['cadence_hours'],enabled=source['enabled'],verified=False,status='pending' if source['enabled'] else 'manual_capture'))
    db.commit()


def install_previous_board_candidates(db):
    """Old observed mappings are candidate evidence, never automatic trust."""
    import json
    from pathlib import Path
    path=Path(__file__).parent/'data/previous_tracker_boards.json'
    if not path.exists():return 0
    added=0
    for item in json.loads(path.read_text()):
        company=db.scalar(select(Company).where(Company.name==item['company']))
        if not company:continue
        exists=db.scalar(select(CompanySource.id).where(CompanySource.company_id==company.id,CompanySource.provider==item['provider'],CompanySource.url==item['url']))
        if exists:continue
        db.add(CompanySource(company_id=company.id,provider=item['provider'],url=item['url'],config={**item['config'],'registry_source':'owner_previous_tracker','association_status':'candidate','association_evidence':item['evidence']},enabled=True,verified=False,priority=2,cadence_hours=24,status='pending'))
        added+=1
    db.commit()
    return added

def bootstrap():
    init_db()
    with SessionLocal() as db:
        result=seed_database(db);update_managed_seed_filters(db);update_classification_rules(db);install_discovery_sources(db);install_previous_board_candidates(db)
    return result

if __name__=='__main__':print(bootstrap())
