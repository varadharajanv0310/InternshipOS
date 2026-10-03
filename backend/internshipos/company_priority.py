"""Owner-editable employer preferences, separate from verification and role fit."""
import json,re
from pathlib import Path

POLICY=json.loads((Path(__file__).parent/'data/company_priority.json').read_text(encoding='utf-8'))

def matches(name, candidate):
    return bool(re.search(r'(?<!\w)'+re.escape(candidate.lower())+r'(?!\w)',name.lower()))

def default_priority(name):
    for key,score,label in [('priority',100,'Priority employer'),('reputed',75,'Established / specialist employer')]:
        if any(matches(name,n) for n in POLICY[key]):
            return {'score':score,'tier':label,'reason':'Imported from your previous employer preferences; editable, not a hiring probability.','source':'previous_project'}
    return {'score':30,'tier':'Needs company review','reason':'No employer preference recorded. This does not imply the company is bad.','source':'unreviewed'}

def priority(company):
    return (company.metadata_json or {}).get('company_priority') or default_priority(company.name)

def install_priorities(db):
    from sqlalchemy import select
    from .models import Company
    for c in db.scalars(select(Company)).all():
        prior=(c.metadata_json or {}).get('company_priority',{})
        if prior.get('source')!='owner':
            c.metadata_json={**(c.metadata_json or {}),'company_priority':default_priority(c.name)}
    db.commit()
